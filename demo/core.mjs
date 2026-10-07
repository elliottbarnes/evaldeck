// Strict JSON for the browser's explicitly bounded numeric subset.
export function strictJSON(source) {
  if(typeof source!=='string'||source.length>20000)throw Error('Answer exceeds the 20,000-character demo limit.');
  let i=0;
  const fail=message=>{throw Error(`${message} at character ${i+1}.`);};
  const ws=()=>{while(/[\t\r\n ]/.test(source[i]||'\0'))i++;};
  function string(){const start=i++;let closed=false;while(i<source.length){const c=source[i++];if(c==='\\'){i++;continue;}if(c==='"'){closed=true;break;}}if(!closed)fail('Unclosed JSON string');let value;try{value=JSON.parse(source.slice(start,i));}catch{fail('Invalid JSON string');}for(const c of value){const n=c.codePointAt(0);if(n>=0xd800&&n<=0xdfff)fail('Unpaired Unicode surrogate');}return value;}
  function value(depth=0){if(depth>128)fail('JSON nesting exceeds 128 levels');ws();const c=source[i];
    if(c==='"')return string();
    if(c==='{'||c==='['){const object=c==='{',out=object?Object.create(null):[];i++;ws();const end=object?'}':']';if(source[i]===end){i++;return out;}while(true){if(object){if(source[i]!=='"')fail('Expected an object key');const key=string();if(Object.hasOwn(out,key))fail('Duplicate JSON key');ws();if(source[i++]!==':')fail('Expected colon');out[key]=value(depth+1);}else out.push(value(depth+1));ws();if(source[i]===end){i++;return out;}if(source[i++]!==',')fail('Expected comma');ws();}}
    for(const [word,result] of [['true',true],['false',false],['null',null]])if(source.startsWith(word,i)){i+=word.length;return result;}
    const match=source.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if(!match)fail('Expected JSON value');i+=match[0].length;const n=Number(match[0]);if(!Number.isFinite(n))fail('Non-finite JSON number');if(Number.isInteger(n)&&!Number.isSafeInteger(n))fail('Integer exceeds the browser safe-integer range');return n;
  }
  const parsed=value();ws();if(i!==source.length)fail('Unexpected trailing input');return parsed;
}
export function pointer(value,path){if(path==='')return value;for(const part of path.slice(1).split('/')){const key=part.replace(/~1/g,'/').replace(/~0/g,'~');if(Array.isArray(value)){if(!/^(0|[1-9][0-9]*)$/.test(key)||!Number.isSafeInteger(Number(key))||Number(key)>=value.length)throw Error('JSON Pointer not found');value=value[Number(key)];}else if(value!==null&&typeof value==='object'&&Object.hasOwn(value,key))value=value[key];else throw Error('JSON Pointer not found');}return value;}
export function equal(a,b){if(typeof a!==typeof b)return false;if(a===null||b===null||typeof a!=='object')return a===b;if(Array.isArray(a)!==Array.isArray(b))return false;const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));}
export function evaluate(output,checks){if(typeof output!=='string'||output.length>20000)throw Error('Answer exceeds the 20,000-character demo limit.');let parsed,error;try{parsed=strictJSON(output);}catch(e){error=e.message;}
  return checks.map(check=>{const type=check.type,needsJSON=['json','required_keys','number_range'].includes(type)||Object.hasOwn(check,'path');let passed=false,detail='';try{if(needsJSON&&error)throw Error('Invalid JSON: '+error);const actual=needsJSON?pointer(parsed,check.path||''):output;
    if(type==='json'){passed=true;detail='Valid strict JSON';}
    else if(type==='required_keys'){passed=actual!==null&&typeof actual==='object'&&!Array.isArray(actual)&&check.keys.every(k=>Object.hasOwn(actual,k));detail=passed?'Required keys present':'Missing required keys or not an object';}
    else if(type==='equals'){passed=equal(actual,check.value);detail=passed?'Values match':`Expected ${JSON.stringify(check.value)}, got ${JSON.stringify(actual)}`;}
    else if(type==='contains'){passed=typeof actual==='string'&&actual.includes(check.value);detail=passed?'Literal substring found':`Missing case-sensitive substring ${JSON.stringify(check.value)}`;}
    else if(type==='number_range'){passed=typeof actual==='number'&&Number.isFinite(actual)&&(!Object.hasOwn(check,'min')||actual>=check.min)&&(!Object.hasOwn(check,'max')||actual<=check.max);detail=passed?'Number is within the inclusive range':'Not a number in the inclusive range';}
    else throw Error('Unsupported check');
  }catch(e){detail=e.message;}return {passed,detail};});
}
