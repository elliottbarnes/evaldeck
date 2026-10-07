export const $ = id => document.getElementById(id);
export function cell(row, value, className = '') { const el = document.createElement('td'); el.textContent = String(value); el.className = className; row.append(el); return el; }
export function row(table, values) { const tr = document.createElement('tr'); values.forEach(value => cell(tr, value)); table.append(tr); return tr; }
export function metrics(items) { const box = $('metrics'); box.replaceChildren(); for (const [value,label] of items) {const item=document.createElement('div');item.className='metric';const strong=document.createElement('strong');strong.textContent=value;const span=document.createElement('span');span.textContent=label;item.append(strong,span);box.append(item);} }
export function status(message, bad=false) { $('status').textContent=message; $('status').className='status '+(bad?'fail':'pass'); }
export function download(value, name) {const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
