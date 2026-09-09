// Explicit HTTPS handoffs only. No browser scraping, shell commands or cookies.
function https(value) {
  if(typeof value!=='string' || value.length>8192 || /[\x00-\x20\x7f\\]/.test(value)) throw new Error('Use an HTTPS URL without whitespace');
  const url=new URL(value);
  if(url.protocol!=='https:' || url.username || url.password || !url.hostname) throw new Error('Use an HTTPS URL without embedded credentials');
  return url;
}
exports.https=https;
exports.urls = (text, limit=10) => {
  if(typeof text!=='string' || text.length>60000) throw new Error('Selection exceeds 60,000 characters');
  const matches=[...text.matchAll(/https?:\/\/[^\s<>"'`]+/g)].map(m=>({index:m.index,text:m[0].replace(/[),.;!?]+$/g,'')}));
  if(!matches.length) throw new Error('Select one or more HTTPS URLs');
  if(matches.length>limit) throw new Error('Select at most '+limit+' URLs');
  return matches.map(m=>({...m,url:https(m.text).href}));
};
exports.openAll = async (text,pop) => {
  const urls=[...new Set(exports.urls(text).map(m=>m.url))];
  for(const url of urls) await pop.openUrl(url);
};
exports.highlight = (text,page) => {
  const url=https(page.trim());
  if(!text.trim() || text.length>2000) throw new Error('Select 1–2,000 characters to highlight');
  // Hyphens are syntax in text fragments, even though encodeURIComponent leaves
  // them unchanged. Preserve the page fragment, replacing any prior directive.
  const fragment=url.hash.slice(1).split(':~:')[0];
  url.hash=fragment+':~:text='+encodeURIComponent(text.trim()).replace(/-/g,'%2D');
  return url.href;
};
exports.outlook = value => {
  const u=https(value.trim());
  if(!['outlook.office.com','outlook.office365.com','outlook.live.com'].includes(u.hostname)) throw new Error('Copy an Outlook web message URL first');
  if(u.pathname.startsWith('/mail/deeplink/read/')) return u.href;
  const m=/^\/mail\/(?:[^/]+\/)?id\/([^/]+)$/.exec(u.pathname);
  if(!m) throw new Error('Use an Outlook web message URL containing /id/');
  const id=decodeURIComponent(m[1]);
  if(!id || id.length>4096 || /[\x00-\x20\x7f]/.test(id)) throw new Error('Invalid Outlook message ID');
  u.pathname='/mail/deeplink/read/'+encodeURIComponent(id.replace(/[+/]/g,'-'));
  u.search='';u.hash='';u.searchParams.set('ItemID',id);u.searchParams.set('exvsurl','1');
  return u.href;
};
exports.xiaohongshu = text => {
  const m=/https:\/\/[^\s<>"'`]+/.exec(text);
  if(m) {
    const u=https(m[0].replace(/[),.;!?]+$/g,''));
    if(['www.xiaohongshu.com','xiaohongshu.com','xhslink.com','www.xhslink.com'].includes(u.hostname)) return u.href;
  }
  if(text.length>2000) throw new Error('Search text exceeds 2,000 characters');
  return 'https://www.xiaohongshu.com/search_result?keyword='+encodeURIComponent(text.trim());
};
