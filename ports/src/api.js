// Omapop's small, explicit API clients. No upstream OAuth identities, SDKs,
// remote imports, retries, telemetry, persistent chat or automatic publication.
const web=require('./web.js');
const encoder=new TextEncoder();
function setting(o,key,label=key) {
  const value=o[key];
  if(typeof value!=='string' || !value.trim() || value.length>4096 || /[\x00-\x1f\x7f]/.test(value)) {
    const e=new Error('Set '+label+' in this extension’s settings');e.omapopKind='settings';throw e;
  }
  return key==='password'?value:value.trim();
}
function identifier(o,key) {
  const value=setting(o,key);
  if(!/^[\w-]{1,128}$/.test(value)) throw new Error('Invalid '+key);
  return value;
}
function textResult(value,kind='text') {
  if(typeof value!=='string' || !value.length || encoder.encode(value).length>131072) throw new Error('Service returned an empty or oversized result');
  return {kind,value};
}
function status(value='Saved') {return textResult(value,'status');}
function escaped(value) {return value.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);}
function markdownLink(label,url) {return '['+label.replace(/[\\[\]]/g,'\\$&').replace(/\s+/g,' ')+']('+web.https(url).href.replace(/[()]/g,c=>c==='('?'%28':'%29')+')';}
exports.run=async (provider,text,o={},fetcher=globalThis.fetch) => {
  if(typeof text!=='string' || !text.trim() || text.length>60000) throw new Error('Select 1–60,000 characters');
  let calls=0;
  async function request(url,{method='GET',body,headers={},format='json',allowStatus=false}={}) {
    if(++calls>5) throw new Error('At most five requests per action');
    const encoded=body===undefined?undefined:typeof body==='string'?body:JSON.stringify(body);
    if(encoded!==undefined && encoder.encode(encoded).length>131072) throw new Error('Request exceeds 128 KiB');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetcher(url,{method,body:encoded,redirect:'error',credentials:'omit',signal:controller.signal,
        headers:{Accept:format==='json'?'application/json':'*/*','User-Agent':'Omapop/1.0 (+https://github.com/jondkinney/omapop)',...(body!==undefined?{'Content-Type':'application/json'}:{}),...headers}});
      if(allowStatus) {await response.body?.cancel();return response.status;}
      if(!response.ok) throw new Error('Service returned HTTP '+response.status+(response.status===429?' (rate limited)':''));
      const raw=await response.text();
      if(encoder.encode(raw).length>131072) throw new Error('Response exceeds 128 KiB');
      if(format==='text') return raw;
      const data=raw?JSON.parse(raw):{};
      if(!data || typeof data!=='object' || data.error || data.errors || data.errorcode || data.ok===false || data.success===false) throw new Error('Service did not confirm success');
      return data;
    } catch(e) {
      // Never leak an authenticated URL, request headers or response body.
      if(/^Service returned HTTP \d{3}|^Response exceeds|^Service did not confirm/.test(e.message)) throw e;
      throw new Error(controller.signal.aborted?'Request timed out after 20 seconds':'Request failed or returned invalid data');
    } finally {clearTimeout(timer);}
  }
  const token=()=>setting(o,'token','your personal API token');
  const bearer=()=>({Authorization:'Bearer '+token()});
  const oneUrl=()=>web.https(text.trim()).href;
  if(provider==='clickup') {
    const list=identifier(o,'listId');
    const data=await request('https://api.clickup.com/api/v2/list/'+list+'/task',{method:'POST',headers:{Authorization:token()},body:{name:text.split('\n')[0].slice(0,256),description:text}});
    if(!data.id) throw new Error('ClickUp did not return a task ID');return status('Task created');
  }
  if(provider==='todoist') {
    const body={content:text.split('\n')[0].slice(0,500),description:text.includes('\n')?text.slice(text.indexOf('\n')+1):''};
    if(o.projectId) body.project_id=identifier(o,'projectId');
    if(o.due) body.due_string=setting(o,'due');
    const data=await request('https://api.todoist.com/api/v1/tasks',{method:'POST',headers:bearer(),body});
    if(!data.id) throw new Error('Todoist did not return a task ID');return status('Task created');
  }
  if(provider==='raindrop') {
    const id=o.collectionId?Number(o.collectionId):0;
    if(!Number.isSafeInteger(id) || id<0) throw new Error('Use a numeric collection ID');
    const data=await request('https://api.raindrop.io/rest/v1/raindrop',{method:'POST',headers:bearer(),body:{link:oneUrl(),title:o.title||oneUrl(),collection:{$id:id}}});
    if(data.result!==true || !data.item?._id) throw new Error('Raindrop did not return a bookmark');return status('Bookmark saved');
  }
  if(provider==='readwise') {
    if(o.mode==='reader') {
      const data=await request('https://readwise.io/api/v3/save/',{method:'POST',headers:{Authorization:'Token '+token()},body:{url:oneUrl()}});
      if(!data.id) throw new Error('Reader did not return a document ID');return status('Saved to Reader');
    }
    if(text.length>8191) throw new Error('Readwise highlights allow at most 8,191 characters');
    const data=await request('https://readwise.io/api/v2/highlights/',{method:'POST',headers:{Authorization:'Token '+token()},body:{highlights:[{text,title:String(o.title||'Omapop captures').slice(0,511),source_type:'omapop'}]}});
    if(!Array.isArray(data) || !data.length) throw new Error('Readwise did not confirm a highlight');return status('Highlight saved');
  }
  if(provider==='tana') {
    const body={targetNodeId:identifier(o,'nodeId'),nodes:[{name:escaped(text)}]};
    if(JSON.stringify(body).length>5000) throw new Error('Tana payload exceeds 5,000 characters');
    await request('https://europe-west1-tagr-prod.cloudfunctions.net/addToNodeV2',{method:'POST',headers:bearer(),body});return status('Captured to Tana');
  }
  if(provider==='roam') {
    const graph=identifier(o,'graphName');
    const d=new Date(),daily=[String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0'),d.getFullYear()].join('-');
    const location={page:{title:o.pageTitle||{'daily-note-page':daily}}};
    if(o.nestUnder) location['nest-under']={string:setting(o,'nestUnder')};
    await request('https://append-api.roamresearch.com/api/graph/'+graph+'/append-blocks',{method:'POST',headers:bearer(),body:{location,'append-data':[{string:text}]}});return status('Captured to Roam');
  }
  if(provider==='craft') {
    const endpoint=web.https(setting(o,'endpoint','Craft connection API URL'));
    if(endpoint.origin!=='https://connect.craft.do' || !/^\/link\/[\w-]+\/api\/v1\/?$/.test(endpoint.pathname) || endpoint.search || endpoint.hash) throw new Error('Use the connection API URL from Craft settings');
    const data=await request(endpoint.href.replace(/\/$/,'')+'/blocks',{method:'POST',headers:o.token?bearer():{},body:{markdown:text,position:{position:'end',pageId:identifier(o,'pageId')}}});
    if(!Array.isArray(data.items) || !data.items.length) throw new Error('Craft did not return inserted blocks');return status('Captured to Craft');
  }
  if(provider==='buffer') {
    const query='mutation CreateIdea($input: CreateIdeaInput!) { createIdea(input: $input) { __typename ... on Idea { id } ... on IdeaResponse { idea { id } } } }';
    const data=await request('https://api.buffer.com',{method:'POST',headers:bearer(),body:{query,variables:{input:{organizationId:identifier(o,'organizationId'),content:{title:text.split('\n')[0].slice(0,100),text}}}}});
    const result=data.data?.createIdea;
    if(!(result?.id || result?.idea?.id)) throw new Error('Buffer did not create an idea');return status('Idea saved in Buffer');
  }
  if(provider==='slack') {
    const url=web.https(setting(o,'webhook','Slack incoming webhook URL'));
    if(url.origin!=='https://hooks.slack.com' || !/^\/services\/[A-Z0-9]+\/[A-Z0-9]+\/[A-Za-z0-9]+$/.test(url.pathname) || url.search || url.hash) throw new Error('Use a hooks.slack.com incoming webhook');
    if(text.length>3000) throw new Error('Slack capture allows at most 3,000 characters');
    const reply=await request(url.href,{method:'POST',format:'text',body:{text:escaped(text),blocks:[{type:'section',text:{type:'plain_text',text,emoji:false}}],unfurl_links:false,unfurl_media:false}});
    if(reply.trim()!=='ok') throw new Error('Slack did not confirm the message');return status('Sent to the configured Slack channel');
  }
  if(provider==='pinboard') {
    const params=new URLSearchParams({auth_token:token(),format:'json',url:oneUrl(),description:o.title||oneUrl(),shared:o.public?'yes':'no',toread:'yes',replace:'no'});
    const data=await request('https://api.pinboard.in/v1/posts/add?'+params);
    if(data.result_code!=='done') throw new Error('Pinboard did not add the bookmark; it may already exist');return status('Saved to Pinboard');
  }
  if(provider==='instapaper') {
    const body=new URLSearchParams({username:setting(o,'username'),password:setting(o,'password'),url:oneUrl()}).toString();
    await request('https://www.instapaper.com/api/add',{method:'POST',format:'text',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});return status('Saved to Instapaper');
  }
  if(provider==='currency') {
    const m=/^\s*([-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*([A-Za-z]{3})(?:\s+(?:to|in)\s+([A-Za-z]{3}))?\s*$/.exec(text);
    if(!m) throw new Error('Use an amount and currency, for example 10 USD to EUR');
    const amount=Number(m[1].replace(',','.')),from=m[2].toUpperCase(),to=String(m[3]||o.currency||'EUR').toUpperCase();
    if(!Number.isFinite(amount) || Math.abs(amount)>1e12 || !/^[A-Z]{3}$/.test(to)) throw new Error('Invalid amount or currency');
    if(from===to) return textResult(amount.toFixed(2)+' '+to);
    const data=await request('https://api.frankfurter.dev/v2/rate/'+from+'/'+to);
    if(typeof data.rate!=='number' || !Number.isFinite(data.rate) || data.rate<=0 || !/^\d{4}-\d{2}-\d{2}$/.test(data.date)) throw new Error('Exchange service returned an invalid rate');
    return textResult((amount*data.rate).toFixed(2)+' '+to+' (rate '+data.date+')');
  }
  if(provider==='openai' || provider==='ollama') {
    const model=setting(o,'model','model name');
    if(text.length>16000) throw new Error('AI prompts allow at most 16,000 characters');
    if(provider==='openai') {
      const data=await request('https://api.openai.com/v1/responses',{method:'POST',headers:bearer(),body:{model,input:text,instructions:String(o.prompt||'Answer the selected text helpfully.').slice(0,4000),max_output_tokens:2048,store:false}});
      if(data.status!=='completed') throw new Error('Model response was incomplete; choose a smaller task');
      const value=(data.output||[]).filter(x=>x.type==='message').flatMap(x=>x.content||[]).filter(x=>x.type==='output_text').map(x=>x.text).join('\n');
      return textResult(value,'preview');
    }
    const base=new URL(String(o.endpoint||'http://127.0.0.1:11434'));
    if(!['127.0.0.1','localhost','[::1]'].includes(base.hostname) || !['http:','https:'].includes(base.protocol) || base.username || base.password || base.pathname!=='/' || base.search || base.hash) throw new Error('Ollama must use a loopback server URL');
    const data=await request(base.origin+'/api/chat',{method:'POST',body:{model,stream:false,messages:[{role:'system',content:String(o.prompt||'Answer helpfully.').slice(0,4000)},{role:'user',content:text}],options:{num_predict:1024}}});
    if(data.done!==true) throw new Error('Ollama response was incomplete');return textResult(data.message?.content,'preview');
  }
  if(provider==='bitly' || provider==='shorten') {
    const matches=web.urls(text,5),replacements=[];
    for(const match of matches) {
      const data=provider==='bitly'?await request('https://api-ssl.bitly.com/v4/shorten',{method:'POST',headers:bearer(),body:{long_url:match.url}})
        :await request('https://is.gd/create.php?format=json&url='+encodeURIComponent(match.url));
      const url=web.https(provider==='bitly'?data.link:data.shorturl);
      if(provider==='shorten' && url.hostname!=='is.gd') throw new Error('Shortener returned an unexpected host');
      replacements.push(url.href);
    }
    let result=text;
    for(let i=matches.length-1;i>=0;i--) result=result.slice(0,matches[i].index)+replacements[i]+result.slice(matches[i].index+matches[i].text.length);
    return textResult(result);
  }
  if(provider==='wayback') {
    const data=await request('https://archive.org/wayback/available?url='+encodeURIComponent(oneUrl()));
    const snapshot=data.archived_snapshots?.closest;
    if(!snapshot?.available || String(snapshot.status)!=='200') throw new Error('No archived snapshot was found');
    const url=new URL(snapshot.url);
    if(url.hostname!=='web.archive.org' || !['http:','https:'].includes(url.protocol) || url.username || url.password || url.port) throw new Error('Archive returned an unexpected URL');
    url.protocol='https:';return textResult(web.https(url.href).href,'url');
  }
  if(provider==='github') {
    const m=/^([\w.-]+)\/([\w.-]+)(?:#(\d+))?$/.exec(text.trim());
    if(m && !m[1].includes('..') && !m[2].includes('..')) return textResult('https://github.com/'+m[1]+'/'+m[2]+(m[3]?'/issues/'+m[3]:''),'url');
    const data=await request('https://api.github.com/search/repositories?q='+encodeURIComponent(text.trim().slice(0,256))+'&per_page=1',{headers:{Accept:'application/vnd.github+json'}});
    const url=web.https(data.items?.[0]?.html_url);
    if(url.hostname!=='github.com') throw new Error('GitHub returned an unexpected URL');return textResult(url.href,'url');
  }
  if(provider==='searchlink') {
    if(text.length>600 || text.trim().split(/\s+/).length>75) throw new Error('Search allows 600 characters and 75 words');
    const data=await request('https://api.search.brave.com/res/v1/web/search?q='+encodeURIComponent(text.trim())+'&count=1',{headers:{'X-Subscription-Token':token()}});
    const result=data.web?.results?.[0];
    if(!result) throw new Error('No search result found');return textResult(markdownLink(text.trim(),result.url));
  }
  if(provider==='checkurls') {
    const results=[];
    for(const match of web.urls(text,5)) {
      let value;
      try {value=String(await request(match.url,{method:'HEAD',allowStatus:true}));} catch {value='Unavailable or redirected';}
      results.push(value+' — '+match.url);
    }
    return textResult(results.join('\n'),'preview');
  }
  if(provider==='webmarkdown') {
    const html=await request(oneUrl(),{format:'text'});
    return textResult(require('./markup.js').markdown(html));
  }
  throw new Error('Unknown API client');
};
exports.invoke=async (provider,pop) => {
  try {
    const result=await exports.run(provider,pop.input.text,pop.options);
    if(result.kind==='status') await pop.showText(result.value);
    else if(result.kind==='url') await pop.openUrl(result.value);
    else if(result.kind==='preview') await pop.showText(result.value,{preview:true});
    else {await pop.copyText(result.value,{notify:false});await pop.showText(result.value,{preview:true});}
  } catch(e) {if(e.omapopKind==='settings') throw pop.settingsRequiredError(e.message);throw e;}
};
