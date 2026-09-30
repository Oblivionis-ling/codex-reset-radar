"""Bounded browser context jobs on the existing durable queue; no network I/O."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_DEPTH = 3
MAX_TEXT = 12000
LEASE_SECONDS = 90
WAIT_SECONDS = 100
MAX_ATTEMPTS = 3
RETRY_SECONDS = 300
REASONS = {"RELATION_UNCONFIRMED", "BROWSER_DISCONNECTED", "LOGIN_REQUIRED", "PAGE_LOADING",
           "NETWORK_OR_RATE_LIMIT", "BODY_UNAVAILABLE", "INCOMPLETE_CONTENT", "USER_NAVIGATED"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS reply_context_nodes(
 tweet_id TEXT PRIMARY KEY, body_json TEXT NOT NULL, content_hash TEXT NOT NULL, observed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reply_context_history(
 tweet_id TEXT NOT NULL, content_hash TEXT NOT NULL, body_json TEXT NOT NULL, observed_at TEXT NOT NULL,
 PRIMARY KEY(tweet_id,content_hash));
CREATE TABLE IF NOT EXISTS reply_context_inputs(
 input_hash TEXT PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES tibo_posts(id), input_json TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_reply_context_history_as_of
 ON reply_context_history(tweet_id,observed_at DESC);
"""

def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class ReplyContexts:
    def __init__(self, database):
        self.db = database

    def ensure(self, tweet_id: str) -> None:
        if not re.fullmatch(r"\d{1,25}", tweet_id):
            return
        with self.db.connect() as c:
            c.execute("""INSERT INTO processing_jobs(job_type,entity_key,payload_json,status,attempts,created_at,updated_at)
                       VALUES('REPLY_CONTEXT',?,?,'PENDING',0,?,?) ON CONFLICT(job_type,entity_key) DO NOTHING""",
                      (tweet_id, json.dumps({"tweet_id": tweet_id}), now(), now()))

    def job(self, tweet_id: str) -> dict | None:
        with self.db.connect() as c:
            r = c.execute("SELECT * FROM processing_jobs WHERE job_type='REPLY_CONTEXT' AND entity_key=?", (tweet_id,)).fetchone()
        return dict(r) if r else None

    def claim(self) -> dict | None:
        stamp = now()
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("""UPDATE processing_jobs SET status=CASE WHEN attempts>=? THEN 'FAILED' ELSE 'PENDING' END,
                       last_error='BROWSER_DISCONNECTED' WHERE job_type='REPLY_CONTEXT' AND status='RUNNING' AND next_attempt_at<=?""",
                      (MAX_ATTEMPTS, stamp))
            if c.execute("SELECT 1 FROM processing_jobs WHERE job_type='REPLY_CONTEXT' AND status='RUNNING'").fetchone():
                return None
            row = c.execute("""SELECT * FROM processing_jobs WHERE job_type='REPLY_CONTEXT' AND status='PENDING'
                AND attempts<? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY id LIMIT 1""", (MAX_ATTEMPTS, stamp)).fetchone()
            if not row:
                return None
            token = secrets.token_hex(16)
            payload = {"tweet_id": row["entity_key"], "lease": token}
            expiry = (datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat().replace('+00:00','Z')
            c.execute("UPDATE processing_jobs SET status='RUNNING',payload_json=?,attempts=attempts+1,next_attempt_at=?,updated_at=? WHERE id=?",
                      (json.dumps(payload), expiry, stamp, row['id']))
        return {"id": row['id'], **payload, "lease_seconds": LEASE_SECONDS, "max_depth": MAX_DEPTH}

    @staticmethod
    def _validate_node(node: dict, *, allow_fixture_ids: bool = False) -> dict:
        tid, author = str(node.get('tweet_id','')), str(node.get('author',''))
        identifier = r'(?:\d{1,25}|SYN:[A-Z0-9_-]{1,20}:\d{3})' if allow_fixture_ids else r'\d{1,25}'
        if not re.fullmatch(identifier, tid) or not re.fullmatch(r'[A-Za-z0-9_]{1,30}',author):
            raise ValueError('invalid context identity')
        text = str(node.get('text',''))
        if not text.strip() or len(text)>MAX_TEXT:
            raise ValueError('invalid context body')
        posted = datetime.fromisoformat(str(node['posted_at']).replace('Z','+00:00'))
        if posted.tzinfo is None:
            raise ValueError('context requires timezone')
        parent = node.get('parent_id')
        if parent is not None and (not re.fullmatch(identifier, str(parent)) or str(parent)==tid):
            raise ValueError('invalid direct parent')
        if node.get('relation_source') not in {'x_replied_to_field','canonical_body_only'}:
            raise ValueError('direct reply relation must be observed, not inferred from DOM order')
        if node.get('relation_source')=='canonical_body_only' and parent is not None:
            raise ValueError('cached body cannot establish an unobserved relation')
        url = node.get('url')
        if url is None and tid.isdigit():
            url = f'https://x.com/{author}/status/{tid}'
        return {'tweet_id':tid, 'author':author, 'text':text, 'posted_at':posted.astimezone(UTC).isoformat().replace('+00:00','Z'),
                'parent_id':parent, 'relation_source':node['relation_source'], 'language':str(node.get('language','unknown'))[:15],
                'completeness':node.get('completeness') if node.get('completeness') in {'complete','partial','media_incomplete'} else 'partial',
                'url':url, 'use':'context-only'}

    @staticmethod
    def validate_node(node: dict) -> dict:
        # Browser/API completion stays restricted to real X IDs.
        return ReplyContexts._validate_node(node)

    @staticmethod
    def _persist_observation(connection, node: dict, observed_at: str) -> str:
        body, version = json.dumps(node,ensure_ascii=False), digest(node)
        connection.execute('INSERT OR IGNORE INTO reply_context_history VALUES(?,?,?,?)',
                           (node['tweet_id'],version,body,observed_at))
        connection.execute('''INSERT INTO reply_context_nodes VALUES(?,?,?,?)
            ON CONFLICT(tweet_id) DO UPDATE SET body_json=excluded.body_json,
            content_hash=excluded.content_hash,observed_at=excluded.observed_at
            WHERE reply_context_nodes.observed_at<=excluded.observed_at''',
            (node['tweet_id'],body,version,observed_at))
        return version

    def record_observation(self, node: dict, observed_at: str, *, allow_fixture_ids: bool = False) -> str:
        """Persist one already-observed context node through the shared history path."""
        clean = self._validate_node(node, allow_fixture_ids=allow_fixture_ids)
        parsed = datetime.fromisoformat(str(observed_at).replace('Z','+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('context observation requires timezone')
        stamp = parsed.astimezone(UTC).isoformat().replace('+00:00','Z')
        with self.db.connect() as c:
            return self._persist_observation(c,clean,stamp)

    def expected_target_author(self, tweet_id: str, as_of: str | None = None) -> str:
        return 'thsottiaux'

    def complete(self, job_id: int, lease: str, nodes: list[dict], reason: str | None = None) -> bool:
        if len(nodes)>MAX_DEPTH+1 or sum(len(str(n.get('text',''))) for n in nodes)>MAX_TEXT:
            raise ValueError('context bound exceeded')
        clean = [self.validate_node(n) for n in nodes]
        if clean and clean[0]['relation_source']!='x_replied_to_field':
            raise ValueError('target direct relation must be confirmed')
        for node in clean:
            if node['relation_source']=='canonical_body_only':
                own=self.db.get_post_by_tweet_id(node['tweet_id'])
                if not own or own['original_text']!=node['text'] or node['author']!='thsottiaux':
                    raise ValueError('cached body must match canonical content')
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            job = c.execute("SELECT * FROM processing_jobs WHERE id=? AND job_type='REPLY_CONTEXT'",(job_id,)).fetchone()
            if not job or job['status']!='RUNNING' or json.loads(job['payload_json']).get('lease')!=lease or job['next_attempt_at']<now():
                return False
            expected = job['entity_key']
            visited = set()
            for node in clean:
                if node['tweet_id']!=expected or expected in visited:
                    raise ValueError('context is not the confirmed direct ancestor chain')
                visited.add(expected)
                expected = node['parent_id']
            target_post = c.execute('SELECT * FROM tibo_posts WHERE tweet_id=?',(job['entity_key'],)).fetchone()
            if target_post and clean and clean[0]['author'].lower()!='thsottiaux':
                raise ValueError('target author is not Tibo')
            stamp = now()
            for node in clean:
                self._persist_observation(c,node,stamp)
            ready = bool(clean and (clean[0]['parent_id'] is None or len(clean)>1))
            error = reason if reason in REASONS else ('BODY_UNAVAILABLE' if not ready else None)
            retry = error in {'PAGE_LOADING','NETWORK_OR_RATE_LIMIT','BROWSER_DISCONNECTED','BODY_UNAVAILABLE'} and job['attempts']<MAX_ATTEMPTS
            retry_at = (datetime.now(UTC)+timedelta(seconds=RETRY_SECONDS)).isoformat().replace('+00:00','Z') if retry else None
            c.execute('UPDATE processing_jobs SET status=?,last_error=?,next_attempt_at=?,updated_at=? WHERE id=?',
                      ('PENDING' if retry else 'COMPLETED' if ready else 'FAILED',error,retry_at,stamp,job_id))
        # Normal authenticated page response supplies original text, not browser translation.
        # Existing content policies remain attached to the old hash and require review.
        for node in clean:
            existing=self.db.get_post_by_tweet_id(node['tweet_id'])
            if existing and node['author'].lower()=='thsottiaux' and node['relation_source']=='x_replied_to_field':
                self.db.upsert_posts_detailed([{ 'tweet_id':node['tweet_id'], 'text':node['text'], 'posted_at':node['posted_at'],
                    'is_reply':node['parent_id'] is not None,'reply_to_tweet_id':node['parent_id'],
                    'url':node['url'],'source':'context_detail_original'}])
        return True

    def node(self, tweet_id: str, as_of: str | None = None) -> dict | None:
        with self.db.connect() as c:
            if as_of:
                cutoff = datetime.fromisoformat(str(as_of).replace('Z','+00:00'))
                if cutoff.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=UTC)
                cutoff_stamp = cutoff.astimezone(UTC).isoformat().replace('+00:00','Z')
                row = c.execute('''SELECT tweet_id,body_json,content_hash,observed_at
                    FROM reply_context_history WHERE tweet_id=? AND observed_at<=?
                    ORDER BY observed_at DESC,rowid DESC LIMIT 1''',(tweet_id,cutoff_stamp)).fetchone()
                from_history = row is not None
                if row is None:
                    row = c.execute('SELECT * FROM reply_context_nodes WHERE tweet_id=?',(tweet_id,)).fetchone()
                    if row and datetime.fromisoformat(row['observed_at'].replace('Z','+00:00')).astimezone(UTC)>cutoff.astimezone(UTC):
                        row = None
            else:
                row = c.execute('SELECT * FROM reply_context_nodes WHERE tweet_id=?',(tweet_id,)).fetchone()
                from_history = False
        if not row:
            own=self.db.get_post_by_tweet_id(tweet_id)
            if own and not as_of and own['original_language']=='en' and own['original_text']:
                if not all(self.db.content_use_allowed(own,u) for u in ('analysis','judge_evidence')):
                    return {'tweet_id':tweet_id,'restricted':True}
                return {'tweet_id':tweet_id,'author':self.expected_target_author(tweet_id),'text':own['original_text'],
                        'language':own['original_language'],'posted_at':own['posted_at'],'parent_id':None,
                        'url':own['url'],'relation_source':'canonical_body_only','completeness':'complete',
                        'content_hash':own['text_hash'],'use':'context-only'}
            return None
        body = json.loads(row['body_json'])
        own = self.db.get_post_by_tweet_id(tweet_id)
        if own:
            if not all(self.db.content_use_allowed(own,u) for u in ('analysis','judge_evidence')):
                return {'tweet_id':tweet_id,'restricted':True}
            expected_author = self.expected_target_author(tweet_id, as_of)
            if body['author'].lower()!=expected_author.lower():
                return {'tweet_id':tweet_id,'restricted':True}
            current_text = own['original_text']
            current_parent = own.get('reply_to_tweet_id') if own.get('is_reply') else None
            current_changed = body.get('text') != current_text or body.get('parent_id') != current_parent
            if as_of:
                cutoff = datetime.fromisoformat(str(as_of).replace('Z','+00:00'))
                if cutoff.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=UTC)
                updated = own.get('updated_at')
                updated_at = datetime.fromisoformat(str(updated).replace('Z','+00:00')) if updated else None
                changed_after_cutoff = bool(updated_at and updated_at.astimezone(UTC)>cutoff.astimezone(UTC))
                if changed_after_cutoff and current_changed and not from_history:
                    return None  # A live-row snapshot is not proof of a historical version.
                if not changed_after_cutoff:
                    body = {**body,'text':current_text,'language':own['original_language'],
                            'parent_id':current_parent,
                            'relation_source':'x_replied_to_field' if body.get('relation_source')=='x_replied_to_field' else body.get('relation_source')}
            else:
                body = {**body,'text':current_text,'language':own['original_language'],'parent_id':current_parent,
                        'relation_source':'x_replied_to_field' if body.get('relation_source')=='x_replied_to_field' else body.get('relation_source')}
            # Canonical content is reused rather than counted as a second target post.
            body = {**body,'canonical_post_id':own['id']}
        return {**body,'content_hash':digest(body)}

    def snapshot(self, post: dict, as_of: str | None = None) -> dict:
        if not post.get('is_reply'):
            return {'state':'NOT_REQUIRED','nodes':[],'missing':[]}
        target = self.node(post['tweet_id'], as_of)
        chain, missing, seen = [], [], {post['tweet_id']}
        parent = target.get('parent_id') if target and not target.get('restricted') else None
        if not target or target.get('relation_source')=='canonical_body_only':
            missing.append('RELATION_UNCONFIRMED')
        elif target.get('restricted'):
            missing.append('CONTENT_RESTRICTED')
        for depth in range(MAX_DEPTH):
            if not parent: break
            if parent in seen:
                missing.append('RELATION_CYCLE');break
            seen.add(parent)
            node = self.node(parent, as_of)
            if not node or node.get('restricted'):
                missing.append('CONTENT_RESTRICTED' if node else 'BODY_UNAVAILABLE');break
            if post.get('posted_at') and datetime.fromisoformat(node['posted_at'].replace('Z','+00:00'))>datetime.fromisoformat(post['posted_at'].replace('Z','+00:00')):
                missing.append('TIME_CONFLICT');break
            if not post.get('posted_at'): missing.append('TIME_UNAVAILABLE')
            chain.append({**node,'depth':depth+1})
            if node['relation_source']=='canonical_body_only': missing.append('ANCESTOR_RELATION_UNCONFIRMED')
            if node['completeness']!='complete': missing.append('INCOMPLETE_CONTENT')
            parent=node['parent_id']
        if parent and len(chain)==MAX_DEPTH: missing.append('DEPTH_LIMIT')
        return {'state':'READY' if not missing else 'PARTIAL' if chain else 'UNAVAILABLE', 'nodes':chain, 'missing':missing,
                'direct_parent_id':target.get('parent_id') if target else None}

    def input(self, post: dict, as_of: str | None = None) -> dict:
        historical = post.get('_historical_input')
        if historical:
            snapshot = historical['snapshot']
            result = {**post,'reply_context':snapshot['reply_context'],'input_hash':historical['input_hash']}
            result.pop('_historical_input',None)
            return result
        context = self.snapshot(post,as_of)
        identity = digest({'text_hash':post['text_hash'],'reply_context':context}) if post.get('is_reply') else post['text_hash']
        return {**post,'reply_context':context,'input_hash':identity}

    def archive_input(self, post: dict) -> None:
        with self.db.connect() as c:
            c.execute('INSERT OR IGNORE INTO reply_context_inputs VALUES(?,?,?,?)',
                      (post['input_hash'],post['id'],json.dumps({'tweet_id':post['tweet_id'],'text':post['original_text'],
                       'text_hash':post.get('text_hash'),'posted_at':post['posted_at'],'is_reply':post.get('is_reply'),
                       'reply_to_tweet_id':post.get('reply_to_tweet_id'),'reply_context':post['reply_context'],
                       'author_handle':post.get('author_handle'),'record_role':post.get('record_role'),
                       'content_metadata':post.get('content_metadata')},ensure_ascii=False),now()))

    def waiting(self, post: dict) -> bool:
        job=self.job(post['tweet_id'])
        return bool(job and job['status'] in {'PENDING','RUNNING'} and
                    (datetime.now(UTC)-datetime.fromisoformat(job['created_at'].replace('Z','+00:00'))).total_seconds()<WAIT_SECONDS)
