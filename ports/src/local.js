// Omapop local text tools. No network, filesystem writes, eval or subprocesses.
const MAX_TEXT = 60000;
const MAX_OUTPUT = 131072;
const encoder = new TextEncoder();
function input(value) {
  if (typeof value !== 'string' || value.length > MAX_TEXT) throw new Error('Selection exceeds 60,000 characters');
  return value.replace(/\r\n?/g, '\n');
}
function output(value) {
  if (value.length > MAX_OUTPUT || encoder.encode(value).length > MAX_OUTPUT) throw new Error('Result exceeds 128 KiB');
  return value;
}
function integer(value, minimum, maximum, label) {
  const n = Number(value);
  if (!Number.isSafeInteger(n) || n < minimum || n > maximum) throw new Error(label + ' must be ' + minimum + '–' + maximum);
  return n;
}
function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// Bounded expression parser. Deliberately excludes JS syntax, assignments,
// property access and extension-defined functions.
function calculate(source, variables = {}) {
  source = String(source).replace(/×/g, '*').replace(/÷/g, '/');
  if (!source.trim() || source.length > 512) throw new Error('Use an expression of 1–512 characters');
  const tokens = []; let offset = 0;
  while (offset < source.length) {
    if (/\s/.test(source[offset])) { offset++; continue; }
    const m = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|^[A-Za-z_]+|^(?:\*\*|[+*/%^(),-])/.exec(source.slice(offset));
    if (!m || tokens.length >= 256) throw new Error('Unsupported or excessive expression syntax');
    tokens.push(m[0]); offset += m[0].length;
  }
  const functions = {abs:Math.abs,sqrt:Math.sqrt,cbrt:Math.cbrt,sin:Math.sin,cos:Math.cos,tan:Math.tan,
    asin:Math.asin,acos:Math.acos,atan:Math.atan,log:Math.log,ln:Math.log,log10:Math.log10,exp:Math.exp,
    floor:Math.floor,ceil:Math.ceil,round:Math.round,trunc:Math.trunc,min:Math.min,max:Math.max,pow:Math.pow,hypot:Math.hypot};
  const constants = {pi:Math.PI,e:Math.E,tau:2*Math.PI,...variables};
  let position = 0;
  function expression(minimum = 0, depth = 0) {
    if (depth > 32) throw new Error('Expression nesting exceeds 32 levels');
    let token = tokens[position++], value;
    if (token === '+' || token === '-') value = (token === '-' ? -1 : 1) * expression(25, depth + 1);
    else if (token === '(') {
      value = expression(0, depth + 1);
      if (tokens[position++] !== ')') throw new Error('Missing closing parenthesis');
    } else if (token && /^(?:\d|\.)/.test(token)) value = Number(token);
    else if (token && Object.hasOwn(functions, token.toLowerCase()) && tokens[position] === '(') {
      position++; const args = [];
      do {
        if (args.length >= 10) throw new Error('Too many function arguments');
        args.push(expression(0, depth + 1));
        if (tokens[position] !== ',') break;
        position++;
      } while (true);
      if (tokens[position++] !== ')') throw new Error('Missing function parenthesis');
      value = functions[token.toLowerCase()](...args);
    } else if (token && Object.hasOwn(constants, token.toLowerCase())) value = constants[token.toLowerCase()];
    else throw new Error('Unknown expression term');
    while (position < tokens.length) {
      const op = tokens[position], priority = ({'+':10,'-':10,'*':20,'/':20,'%':20,'^':30,'**':30})[op];
      if (priority === undefined || priority < minimum) break;
      position++;
      const rhs = expression(priority + (op === '^' || op === '**' ? 0 : 1), depth + 1);
      value = op === '+' ? value + rhs : op === '-' ? value - rhs : op === '*' ? value * rhs : op === '/' ? value / rhs
        : op === '%' ? value % rhs : value ** rhs;
      if (!Number.isFinite(value)) throw new Error('Calculation is not finite');
    }
    if (!Number.isFinite(value)) throw new Error('Calculation is not finite');
    return value;
  }
  const result = expression();
  if (position !== tokens.length) throw new Error('Unexpected expression token');
  return result;
}
exports.calculate = text => String(calculate(input(text)));

exports.wrap = (text, opts = {}) => {
  const width = integer(opts.column ?? 80, 1, 1000, 'Column');
  const rows = [];
  for (const line of input(text).split('\n')) {
    const chars = [...line];
    let start = 0;
    while (chars.length - start > width) {
      let end = start + width;
      for (let i = end; i > start; i--) if (chars[i] === ' ') { end = i; break; }
      rows.push(chars.slice(start, end).join(''));
      start = end;
      while (chars[start] === ' ') start++;
    }
    rows.push(chars.slice(start).join(''));
  }
  return output(rows.join('\n'));
};
exports.unwrap = text => output(input(text).split(/(\n[ \t]*\n+)/).map((p,i) => i % 2 ? p : p.replace(/([^\n])[ \t]*\n[ \t]*(?=\S)/g,'$1 ')).join(''));
exports.comment = (text, opts = {}) => {
  const prefix = String(opts.comment_prefix ?? '//');
  if (!prefix || prefix.length > 32 || /[\r\n]/.test(prefix)) throw new Error('Use a comment prefix of 1–32 characters');
  const lines = input(text).split('\n');
  const strip = new RegExp('^([ \\t]*)' + escapeRegex(prefix) + ' ?');
  const commented = lines.filter(line => line.trim()).every(line => strip.test(line));
  return output(lines.map(line => commented ? line.replace(strip,'$1') : line.replace(/^([ \t]*)/,(_,indent)=>indent+prefix+' ')).join('\n'));
};
exports.repeat = text => {
  const match = /^([\s\S]*?)[.*](\+?\d+)$/.exec(input(text));
  if (!match) throw new Error('Use text*COUNT or text.COUNT');
  const count = integer(match[2], 0, 1000, 'Repeat count');
  if (encoder.encode(match[1]).length * count > MAX_OUTPUT) throw new Error('Repeated text exceeds 128 KiB');
  return match[1].repeat(count);
};
exports.mosaic = (text, opts = {}) => {
  const count = [...input(text)].length, mask = String(opts['mosaic-code'] ?? '*');
  if (!mask || mask.length > 16 || encoder.encode(mask).length * count > MAX_OUTPUT) throw new Error('Mask would exceed the result limit');
  return mask.repeat(count);
};
exports.array = (text, opts = {}) => {
  let lines = input(text).split('\n');
  if (opts.trim !== false) lines = lines.map(x => x.trim());
  if (opts.remove_empty_line !== false) lines = lines.filter(Boolean);
  const quote = opts.quotes === 'single' ? "'" : '"';
  const values = lines.map(line => {
    const json = JSON.stringify(line);
    return quote === '"' ? json : "'" + json.slice(1,-1).replace(/\\"/g,'"').replace(/'/g,"\\'") + "'";
  });
  const sep = opts.single_line ? ',' : ',\n';
  const body = values.join(sep) + (opts.last_comma && values.length ? ',' : '');
  return output(opts.add_brackets === false ? body : opts.single_line ? '[' + body + ']' : '[\n' + body + '\n]');
};
function words(text) {
  return input(text).replace(/(\p{Lu})(\p{Lu}\p{Ll})/gu,'$1 $2').replace(/([\p{Ll}\p{N}])(\p{Lu})/gu,'$1 $2').match(/[\p{L}\p{N}]+/gu) || [];
}
function capital(text) { const chars = [...text]; return (chars.shift() || '').toUpperCase() + chars.join(''); }
exports.case = (text, opts = {}) => {
  const list = words(text).map(w => w.toLowerCase()), style = opts.style || 'camel';
  if (style === 'camel') return output(list.map((w,i)=>i?capital(w):w).join(''));
  if (style === 'pascal') return output(list.map(capital).join(''));
  if (style === 'constant') return output(list.join('_').toUpperCase());
  if (style === 'title') return output(list.map(capital).join(' '));
  const separator = {snake:'_',kebab:'-',dot:'.',path:'/'}[style];
  if (separator === undefined) throw new Error('Unknown naming style');
  return output(list.join(separator));
};
exports.variable = text => exports.case(text,{style:input(text).trim().includes('_')?'pascal':'snake'});
exports.slug = text => output(words(input(text).normalize('NFKD').replace(/\p{M}/gu,'')).join('-').toLowerCase());
exports.rot13 = text => input(text).replace(/[A-Za-z]/g,c=>String.fromCharCode(c.charCodeAt(0)+(c.toLowerCase()<='m'?13:-13)));
exports.quote = (text, opts = {}) => {
  const styles = ['“…”','‘…’','"…"',"'…'",'`…`','«…»','《…》','‹…›','»…«','›…‹','「…」','『…』','„…“','‚…‘'];
  const style = styles[integer(opts.style ?? 0,0,styles.length-1,'Quote style')];
  return output(style[0] + input(text) + style[2]);
};
exports.commaJoin = text => output(input(text).split('\n').map(x=>x.trim()).filter(Boolean).map(x=>/[,"]/.test(x)?'"'+x.replace(/"/g,'""')+'"':x).join(', '));
exports.commaSplit = text => {
  text = input(text); const result = []; let cell = '', quoted = false;
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(c==='"') { if(quoted && text[i+1]==='"') {cell+='"';i++;} else quoted=!quoted; }
    else if(c===',' && !quoted) {result.push(cell.trim());cell='';}
    else cell+=c;
  }
  if(quoted) throw new Error('Unclosed CSV quote');
  result.push(cell.trim()); return output(result.join('\n'));
};
exports.sum = (text, opts = {}) => {
  text=input(text); const group=String(opts.separator ?? ','), decimal=String(opts.delimiter ?? '.');
  if(!/^[.,]$/.test(decimal) || !/^[., '\u00a0]?$/.test(group) || group===decimal) throw new Error('Choose distinct single-character grouping and decimal separators');
  const grouped=group?'(?:\\d{1,3}(?:'+escapeRegex(group)+'\\d{3})+|\\d+)':'\\d+';
  const valid=new RegExp('^[-+]?(?:'+grouped+'(?:'+escapeRegex(decimal)+'\\d+)?|'+escapeRegex(decimal)+'\\d+)$');
  const separators=escapeRegex(group+decimal);
  const pattern=new RegExp('[-+]?(?:\\d+(?:['+separators+']\\d+)*|'+escapeRegex(decimal)+'\\d+)','g');
  const numbers=[];let places=0;
  for(const m of text.matchAll(pattern)) {
    if(!valid.test(m[0])) throw new Error('Invalid numeric grouping for the selected separators');
    if(/^[eE][-+]?\d/.test(text.slice(m.index+m[0].length))) throw new Error('Sum expects decimal numbers, without scientific notation');
    if(m[0].length>64 || numbers.length>=5000) throw new Error('Too many or oversized numbers');
    const s=(group?m[0].split(group).join(''):m[0]).replace(decimal,'.');
    const precision=(s.split('.')[1]||'').length;
    if(precision>18) throw new Error('At most 18 decimal places are supported');
    places=Math.max(places,precision);numbers.push(s);
  }
  if(!numbers.length) throw new Error('No numbers found');
  if(places===1) places=2;
  let total=0n;
  for(const s of numbers) {
    const negative=s[0]==='-', parts=s.replace(/^[-+]/,'').split('.');
    total+=(negative?-1n:1n)*BigInt(parts[0]+(parts[1]||'').padEnd(places,'0'));
  }
  const sign=total<0n?'-':'', raw=String(total<0n?-total:total).padStart(places+1,'0');
  let whole=places?raw.slice(0,-places):raw;
  if(opts.formatoutput && group) whole=whole.replace(/\B(?=(\d{3})+(?!\d))/g,()=>group);
  return sign+whole+(places?decimal+raw.slice(-places):'');
};
exports.increment = text => {
  text=input(text);
  const numeric=/(\?:)?##(-?\d+)(?:\.\.(-?\d+))?\.\.(-?\d+)##/.exec(text);
  const array=numeric?null:/##([^#]*,[^#]*)##/.exec(text);
  if(!numeric && !array) throw new Error('Use ##START..END##, ##START..STEP..END## or ##a,b,c##');
  let values;
  if(numeric) {
    const start=integer(numeric[2],-1e12,1e12,'Start'), end=integer(numeric[4],-1e12,1e12,'End');
    const step=numeric[3]===undefined?(end>=start?1:-1):integer(numeric[3],-1e12,1e12,'Step');
    if(!step || (end-start)*step<0) throw new Error('Step must be nonzero and point toward the end');
    const count=Math.floor((end-start)/step)+1;
    if(count>1000) throw new Error('At most 1,000 rows can be generated');
    const width=Math.min(numeric[2].replace(/^-/,'').length,32);
    values=Array.from({length:count},(_,i)=>numeric[1]?'':String(start+i*step).replace(/^(\-?)(\d+)$/,(_,sign,n)=>sign+n.padStart(width,'0')));
  } else values=array[1].split(',').map(x=>x.trim());
  if(values.length>1000) throw new Error('At most 1,000 rows can be generated');
  const match=numeric||array, template=text.slice(0,match.index)+'\u0000'+text.slice(match.index+match[0].length);
  if(text.includes('\u0000')) throw new Error('NUL is not supported in templates');
  const rows=[];let size=0;
  for(let i=0;i<values.length;i++) {
    let row=template.replace('\u0000',()=>values[i]);
    row=row.replace(/##([^#]*?)(?:#([^#]+))?##/g,(_,expression,choices)=>{
      if(array && /^[0x]$/.test(expression)) return values[i];
      const value=Math.trunc(calculate(expression||'x',{x:i+1,i}));
      if(choices!==undefined) return choices.split(',')[value]?.trim()||'';
      const width=Math.min((expression.match(/^0+\d*/) || [''])[0].length,32);
      return String(value).padStart(width,'0');
    });
    size+=encoder.encode(row).length+1;
    if(size>MAX_OUTPUT) throw new Error('Generated text exceeds 128 KiB');
    rows.push(row);
  }
  return rows.join('\n');
};
exports.characters = text => String([...input(text)].length);
exports.lines = text => String(input(text).split('\n').length);
exports.words = text => String([...new Intl.Segmenter(undefined,{granularity:'word'}).segment(input(text))].filter(x=>x.isWordLike).length);
exports.json = (text, opts = {}) => {
  let value=JSON.parse(input(text));const pending=[[value,0]];let count=0;
  while(pending.length) {
    const [item,depth]=pending.pop();
    if(++count>8192 || depth>64) throw new Error('JSON exceeds 8,192 values or 64 levels');
    if(item && typeof item==='object') for(const v of Object.values(item)) pending.push([v,depth+1]);
  }
  const pointer=String(opts.pointer||'');
  if(pointer && !pointer.startsWith('/')) throw new Error('JSON Pointer must begin with /');
  for(const segment of (pointer?pointer.slice(1).split('/'):[])) {
    const key=segment.replace(/~1/g,'/').replace(/~0/g,'~');
    if(value===null || typeof value!=='object' || !Object.hasOwn(value,key)) throw new Error('JSON Pointer does not exist');
    value=value[key];
  }
  return output(JSON.stringify(value,null,opts.minify?0:2));
};

exports.convert = text => {
  const m = /^\s*([-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*(.*?)\s*$/u.exec(input(text));
  if (!m || m[1].length > 32) throw new Error('Select a number and a supported unit');
  const n = Number(m[1].replace(',', '.')), unit = m[2].toLowerCase();
  if (!Number.isFinite(n) || Math.abs(n) > 1e12) throw new Error('Quantity exceeds the conversion limit');
  const conversions = [
    [/^(pounds?|lbs?)$/, 'kg', .45359237], [/^(kilograms?|kilos?|kg)$/, 'lb', 1/.45359237],
    [/^(ounces?|oz)$/, 'g', 28.349523125], [/^(grams?|g)$/, 'oz', 1/28.349523125],
    [/^(inches|inch|ins?|")$/, 'cm', 2.54], [/^(centimetres?|centimeters?|cm)$/, 'in', 1/2.54],
    [/^(millimetres?|millimeters?|mm)$/, 'in', 1/25.4], [/^(feet|foot|ft|')$/, 'm', .3048],
    [/^(yards?|yds?)$/, 'm', .9144], [/^(metres?|meters?|m)$/, 'ft', 1/.3048],
    [/^(miles?|mi)$/, 'km', 1.609344], [/^(kilometres?|kilometers?|km|k)$/, 'mi', 1/1.609344],
  ];
  let value, target;
  if (/^(°?f|(?:degrees? )?fahrenheit)$/.test(unit)) {value=(n-32)*5/9;target='°C';}
  else if (/^(°?c|(?:degrees? )?(?:celsius|centigrade))$/.test(unit)) {value=n*9/5+32;target='°F';}
  else {
    const rule=conversions.find(([pattern])=>pattern.test(unit));
    if (!rule) throw new Error('Unsupported unit');
    value=n*rule[2];target=rule[1];
  }
  const precision=Math.min(6,Math.max(1,(m[1].split(/[.,]/)[1]||'').length));
  return value.toFixed(precision)+(target.startsWith('°')?'':' ')+target;
};

// ISO 9-style transliteration, with Russian, Ukrainian, Belarusian and Serbian
// letters. Literal tables avoid macOS ICU regex and JSON import attributes.
exports.cyrillic = text => {
  const from=[...'абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґўђјљњћџ'];
  const to=['a','b','v','g','d','e','ë','ž','z','i','j','k','l','m','n','o','p','r','s','t','u','f','h','c','č','š','ŝ','ʺ','y','ʹ','è','û','â','ì','ï','ê','g̀','ŭ','đ','j','l̂','n̂','ć','d̂'];
  const map=new Map(from.map((c,i)=>[c,to[i]]));
  return output([...input(text)].map(c=>map.has(c.toLowerCase()) ? (c===c.toUpperCase()?map.get(c.toLowerCase()).toUpperCase():map.get(c)) : c).join(''));
};
exports.htmlEncode = text => output(input(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]));
exports.htmlDecode = text => {
  const entities=require('./entities.json');
  return output(input(text).replace(/&(#(?:x[\da-fA-F]{1,8}|\d{1,10});?|[A-Za-z][A-Za-z0-9]{1,31};)/g,(whole,key)=>{
    if (key[0]!=='#') return Object.hasOwn(entities,key)?entities[key]:whole;
    const hex=key[1]==='x', n=parseInt(key.slice(hex?2:1),hex?16:10);
    return n && n<=0x10ffff && !(n>=0xd800 && n<=0xdfff)?String.fromCodePoint(n):'\ufffd';
  }));
};
