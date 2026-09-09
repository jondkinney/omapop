import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import local from '../ports/src/local.js';

test('calculator parses arithmetic without evaluating JavaScript',()=>{
  for(const [expr,expected] of [['2+3*4','14'],['2^3^2','512'],['-2^2','-4'],['sqrt(9)+max(1,4)','7'],['2^-2','0.25']]) assert.equal(local.calculate(expr),expected);
  for(const expr of ['globalThis','constructor.constructor(1)','1/0','2**99999','sin()','('.repeat(40)+'1'+')'.repeat(40)]) assert.throws(()=>local.calculate(expr));
});
test('literal comments, blank lines, CRLF and Unicode wrapping',()=>{
  assert.equal(local.comment('  abc\r\n  def',{comment_prefix:'/*'}),'  /* abc\n  /* def');
  assert.equal(local.comment('  /* abc\n  /* def',{comment_prefix:'/*'}),'  abc\n  def');
  assert.equal(local.wrap('one two three\n😀😀😀😀\n',{column:3}),'one\ntwo\nthr\nee\n😀😀😀\n😀\n');
  assert.equal(local.unwrap('one\ntwo\n\nthree\nfour'),'one two\n\nthree four');
});
test('arrays escape quotes, backslashes, control characters and Unicode',()=>{
  const lines=['a"b',"a'b",String.raw`a\"b`,String.raw`a\'b`,'a\tb','😀'];
  for(const quotes of ['double','single']) {
    const generated=local.array(lines.join('\n'),{quotes,single_line:true});
    assert.deepEqual(Array.from(vm.runInNewContext(generated,Object.create(null),{timeout:100})),lines);
  }
  assert.equal(local.array('',{single_line:true}),'[]');
});
test('generation bounds reject abusive input before creating large results',()=>{
  assert.equal(local.repeat('ab*3'),'ababab');
  assert.equal(local.mosaic('😀a'),'**');
  for(const fn of [()=>local.repeat('ab*1001'),()=>local.repeat('a'.repeat(1000)+'*1000'),()=>local.mosaic('x'.repeat(60000),{'mosaic-code':'😀'}),()=>local.wrap('a',{column:0}),()=>local.increment('##1..0..5##'),()=>local.increment('##1..1001##'),()=>local.increment('##5..1..1##')]) assert.throws(fn);
});
test('bounded templates support sequences, descending ranges, choices and arithmetic',()=>{
  assert.equal(local.increment('item##01..03##: ##x*2##'),'item01: 2\nitem02: 4\nitem03: 6');
  assert.equal(local.increment('##3..1##'),'3\n2\n1');
  assert.equal(local.increment('##a,b##=##i##'),'a=0\nb=1');
  assert.equal(local.increment('?:##1..2##X##i#red,blue##'),'Xred\nXblue');
  assert.throws(()=>local.increment('##1..2## ##process.exit()##'));
});
test('exact sums avoid binary rounding and validate locale options',()=>{
  assert.equal(local.sum('0.1 0.2'),'0.30');
  assert.equal(local.sum('.2 .3'),'0.50');
  assert.equal(local.sum('1.234,50 + 2.000,25',{separator:'.',delimiter:',',formatoutput:true}),'3.234,75');
  assert.equal(local.sum('9007199254740993 1'),'9007199254740994');
  assert.throws(()=>local.sum('1',{separator:'.',delimiter:'.'}));
  assert.throws(()=>local.sum('1,23'),/grouping/);
  assert.throws(()=>local.sum('1e3'),/scientific/);
  assert.throws(()=>local.sum('0.'+'1'.repeat(19)));
});
test('CSV handles empty, quotes and CR-only input',()=>{
  assert.equal(local.commaJoin('a\rb,c\r"d"'),'a, "b,c", """d"""');
  assert.equal(local.commaSplit('a, "b,c", """d"""'),'a\nb,c\n"d"');
  assert.equal(local.commaJoin(''),'');
  assert.throws(()=>local.commaSplit('"bad'));
});
test('count, casing, HTML entities and units use portable semantics',()=>{
  assert.equal(local.characters('😀a'),'2');
  assert.equal(local.lines('a\rb\r'),'3');
  assert.equal(local.words('Hello, world!'),'2');
  assert.equal(local.variable('__hello__world'),'HelloWorld');
  assert.equal(local.case('XMLHttpRequest',{style:'snake'}),'xml_http_request');
  assert.equal(local.slug('Crème brûlée'),'creme-brulee');
  assert.equal(local.rot13('Hello!'),'Uryyb!');
  assert.equal(local.quote('Hi',{style:10}),'「Hi」');
  assert.equal(local.convert('9,3 cm'),'3.7 in');
  assert.equal(local.convert('-40 °F'),'-40.0°C');
  assert.throws(()=>local.convert('9,3,0 cm'));
  assert.equal(local.cyrillic('Привет Ёж'),'Privet Ëž');
  assert.equal(local.htmlEncode('<&"'), '&lt;&amp;&quot;');
  assert.equal(local.htmlDecode('&copy; &NotEqualTilde; &#x1F600; &#0;'),'© ≂̸ 😀 �');
});
test('JSON Pointer treats special keys as data and bounds recursion',()=>{
  assert.equal(local.json('{"a/b":[2]}',{pointer:'/a~1b/0'}),'2');
  assert.equal(local.json('{"__proto__":3}',{pointer:'/__proto__'}),'3');
  assert.throws(()=>local.json('{}',{pointer:'/constructor'}));
  assert.throws(()=>local.json('['.repeat(65)+'0'+']'.repeat(65)));
});
