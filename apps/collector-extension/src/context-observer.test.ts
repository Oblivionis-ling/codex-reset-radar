import { expect, it, vi } from 'vitest';

it('observes actual replied_to, not conversation root, quotes or adjacent results',async()=>{
  vi.resetModules();
  vi.stubGlobal('location',new URL('https://x.com/i/status/100?crr_context=test'));
  const payload={data:{result:{rest_id:'100',legacy:{full_text:'Synthetic reply',created_at:'2026-09-20T00:00:00Z',
    conversation_id_str:'1',in_reply_to_status_id_str:'90',lang:'en'},core:{user_results:{result:{legacy:{screen_name:'thsottiaux'}}}},
    quoted_status_result:{result:{rest_id:'80',legacy:{full_text:'Quote',conversation_id_str:'80',created_at:'2026-09-19T00:00:00Z'},core:{user_results:{result:{legacy:{screen_name:'quoted'}}}}}}}}};
  const response={ok:true,url:'https://x.com/i/api/graphql/example/TweetDetail',clone:()=>({text:async()=>JSON.stringify(payload)})};
  const page:any={fetch:vi.fn(async()=>response)};vi.stubGlobal('window',page);
  vi.stubGlobal('XMLHttpRequest',class {send() {} });
  await import('./context-observer');await page.fetch('normal-page-request');
  await Promise.resolve();await Promise.resolve();
  expect(page.__crrContext['100'].parent_id).toBe('90');
  expect(page.__crrContext['100'].author).toBe('thsottiaux');
  expect(page.__crrContext['80'].author).toBe('quoted');
});
