// Bounded text conversion. Never loads images, follows links or executes HTML.
const cap=131072;
function bounded(s) {if(typeof s!=='string' || new TextEncoder().encode(s).length>cap) throw new Error('Markup exceeds 128 KiB');return s;}
function decode(s) {return require('./local.js').htmlDecode(s);}
function escapeMarkdown(s) {return s.replace(/[\\`*_[\]<>]/g,'\\$&');}
exports.markdown = html => {
  bounded(html);
  const pieces=[];let hidden=0,pre=0,size=0,count=0;const stack=[];
  const append=s=>{size+=s.length;if(size>cap) throw new Error('Converted markup exceeds 128 KiB');pieces.push(s);};
  const blocks=new Set(['p','div','section','article','header','footer','main','ul','ol','blockquote','tr']);
  for(const match of html.matchAll(/<!--[\s\S]*?(?:-->|$)|<[^>]*>|[^<]+|</g)) {
    if(++count>16000) throw new Error('HTML has too many elements');
    const token=match[0];
    if(token.startsWith('<!--')) continue;
    const tag=/^<\s*(\/?)\s*([a-zA-Z][\w-]*)\b([^>]*)>$/u.exec(token);
    if(!tag) {if(!hidden) append(pre?decode(token):escapeMarkdown(decode(token).replace(/\s+/g,' ')));continue;}
    const close=!!tag[1],name=tag[2].toLowerCase();
    if(['script','style','template','noscript','iframe','svg'].includes(name)) {hidden=Math.max(0,hidden+(close?-1:1));continue;}
    if(hidden) continue;
    if(name==='pre') {pre=Math.max(0,pre+(close?-1:1));append('\n\n```\n');}
    else if(name==='br') append('\n');
    else if(name==='li') append(close?'\n':'\n- ');
    else if(/^h[1-6]$/.test(name)) append(close?'\n\n':'\n\n'+'#'.repeat(Number(name[1]))+' ');
    else if(blocks.has(name)) append('\n\n');
    else if(['b','strong'].includes(name)) append('**');
    else if(['i','em'].includes(name)) append('*');
    else if(name==='code' && !pre) append('`');
    else if(name==='a') {
      if(!close) {
        if(stack.length>=64) throw new Error('HTML links exceed 64 nesting levels');
        const attr=/\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(tag[3]);
        let href=attr?decode(attr[1]??attr[2]??attr[3]):'';
        try {href=require('./web.js').https(href).href.replace(/[()]/g,c=>c==='('?'%28':'%29');} catch {href='';}
        stack.push(href);if(href) append('[');
      } else if(stack.length) {const href=stack.pop();if(href) append(']('+href+')');}
    }
  }
  return bounded(pieces.join('').replace(/\n[ \t]+/g,'\n').replace(/\n{3,}/g,'\n\n').trim());
};
function rtfText(text) {
  let out='';
  for(let i=0;i<text.length;i++) {
    const c=text[i],n=text.charCodeAt(i);
    out+=c==='\\'?'\\\\':c==='{'?'\\{':c==='}'?'\\}':c==='\n'?'\\par\n':c==='\t'?'\\tab ':n>=32 && n<127?c:'\\u'+(n>32767?n-65536:n)+'?';
  }
  return out;
}
exports.rtf = markdown => {
  bounded(markdown);let out='{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 sans-serif;}{\\f1 monospace;}}\n';
  // Basic inline emphasis and code; all literal text is RTF-escaped first.
  // Unsupported Markdown remains literal, including images and raw HTML.
  for(const line of markdown.replace(/\r\n?/g,'\n').split('\n')) {
    const heading=/^(#{1,6})\s+(.*)$/.exec(line);
    const source=heading?heading[2]:line;
    if(heading) out+='{\\b ';
    let pos=0,markers=0;
    while(pos<source.length) {
      const m=/\*\*|__|\*|_|`/.exec(source.slice(pos));
      if(!m || ++markers>2000) {out+=rtfText(source.slice(pos));break;}
      const start=pos+m.index,mark=m[0],end=source.indexOf(mark,start+mark.length);
      out+=rtfText(source.slice(pos,start));
      if(end===-1) {out+=rtfText(source.slice(start));break;}
      const control=mark==='`'?'f1':mark.length===2?'b':'i';
      out+='{\\'+control+' '+rtfText(source.slice(start+mark.length,end))+'}';pos=end+mark.length;
    }
    if(heading) out+='}';out+='\\par\n';
    if(out.length>cap) throw new Error('RTF result exceeds 128 KiB');
  }
  return bounded(out+'}');
};
