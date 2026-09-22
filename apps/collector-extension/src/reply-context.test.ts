import { beforeEach, expect, it, vi } from 'vitest';

let store: Record<string, any>;
let submitted: any;
let cache: Record<string, any>;
let tabs: Record<number, any>;
let job: any;
const sample = (tweet_id: string, parent_id: string | null, author='other') => ({ tweet_id, parent_id, author,
  text:'Synthetic context', posted_at:'2026-09-20T00:00:00Z', relation_source:'x_replied_to_field', completeness:'complete',language:'en' });

beforeEach(() => {
  vi.resetModules();store={};submitted=null;tabs={};
  job={id:1,lease:'test-lease',tweet_id:'100'};
  cache={'100':sample('100','90','thsottiaux'),'90':sample('90',null)};
  vi.stubGlobal('fetch',vi.fn(async (url: string, options: any) => {
    // This test transport has no network fallback, even if local credentials exist.
    if (url.endsWith('/claim')) return {ok:true,json:async()=>({job})};
    if (url.includes('/cache/')) return {ok:true,json:async()=>({node:cache[url.split('/').at(-1)!]??null})};
    if (url.endsWith('/result')) {submitted=JSON.parse(options.body);return {ok:true,json:async()=>({accepted:true})};}
    throw new Error('Unexpected network target');
  }));
  vi.stubGlobal('chrome',{
    storage:{local:{get:vi.fn(async (key:string)=>({[key]:store[key]})),set:vi.fn(async (v:any)=>Object.assign(store,v)),remove:vi.fn(async (key:string)=>{delete store[key];})}},
    tabs:{get:vi.fn(async (id:number)=>tabs[id]),create:vi.fn(async ({url}:any)=>tabs[7]={id:7,url}),update:vi.fn(async (id:number,{url}:any)=>tabs[id]={id,url})},
    scripting:{executeScript:vi.fn(async()=>[{result:{node:sample('100','90','thsottiaux'),login:false}}])}
  });
});

it('reuses cache and submits only the direct chain without opening a tab',async()=>{
  const {runReplyContext}=await import('./reply-context');await runReplyContext();
  expect(submitted.nodes.map((n:any)=>n.tweet_id)).toEqual(['100','90']);
  expect(chrome.tabs.create).not.toHaveBeenCalled();
});

it('worker restart recovers its owned helper and does not touch monitor tabs',async()=>{
  delete cache['100'];
  const url='https://x.com/i/status/80?crr_context=old';
  store.crr_context_owned_tab={tabId:7,url};tabs[7]={id:7,url};tabs[20]={id:20,url:'https://x.com/thsottiaux/with_replies'};
  await (await import('./reply-context')).runReplyContext();
  expect(chrome.tabs.create).not.toHaveBeenCalled();
  expect(chrome.tabs.update).toHaveBeenCalledWith(7,expect.objectContaining({active:false}));
  expect(tabs[20].url).toBe('https://x.com/thsottiaux/with_replies');
  expect(submitted.nodes).toHaveLength(2);
});

it('revokes ownership when the user navigates the helper',async()=>{
  delete cache['100'];store.crr_context_owned_tab={tabId:7,url:'https://x.com/i/status/80?crr_context=old'};
  tabs[7]={id:7,url:'https://x.com/home'};
  await (await import('./reply-context')).runReplyContext();
  expect(chrome.tabs.update).not.toHaveBeenCalled();expect(chrome.tabs.create).not.toHaveBeenCalled();
  expect(submitted.reason).toBe('USER_NAVIGATED');expect(submitted.nodes).toEqual([]);
});

it('never fetches a restricted parent through the browser as a fallback',async()=>{
  cache['90']={restricted:true,tweet_id:'90'};
  await (await import('./reply-context')).runReplyContext();
  expect(submitted.reason).toBe('INCOMPLETE_CONTENT');expect(chrome.tabs.create).not.toHaveBeenCalled();
});

it('rejects arbitrary URL targets supplied as task IDs',async()=>{
  job.tweet_id='https://example.invalid/secret';
  await (await import('./reply-context')).runReplyContext();
  expect(submitted.reason).toBe('RELATION_UNCONFIRMED');expect(chrome.tabs.create).not.toHaveBeenCalled();
});
