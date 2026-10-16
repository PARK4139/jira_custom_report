
// Chip field with fuzzy "skim"-style candidates. Every chosen value is a chip; the input only holds the text being typed.
// Ctrl+Space opens the candidates, or turns the highlighted one into a chip when they are already open;
// Tab (or Enter after arrow keys) also turns the highlighted candidate into a chip.
function fuzzyMatch(query,text){
const needle=query.trim().toLowerCase();if(!needle)return {score:0,indices:[]};
const hay=text.toLowerCase(),whole=hay.indexOf(needle);
if(whole>=0)return {score:200-whole+(whole===0?50:0),indices:[...needle].map((_,i)=>whole+i)};
const indices=[];let score=0,from=0,previous=-2;
for(const char of needle){
if(char===' ')continue;
const at=hay.indexOf(char,from);if(at<0)return null;
score+=1;if(at===0||/[\s(_\-.\/]/.test(hay[at-1]))score+=8;if(at===previous+1)score+=6;score-=(at-from)*.1;
indices.push(at);previous=at;from=at+1;
}
return {score,indices};
}
function rankCandidates(query,candidates,limit){
const ranked=[];
for(const candidate of candidates){const match=fuzzyMatch(query,candidate.label);if(match)ranked.push({candidate,match})}
ranked.sort((a,b)=>b.match.score-a.match.score);
return ranked.slice(0,limit);
}
const COMBO_SEPARATOR=/[,，、;\n]/;
function attachCombo(input,{source,resolve=()=>null,allowRaw=false,onChange,limit=8,delay=0,emptyText=()=>''}){
const box=document.createElement('div');
box.className='chip-field';
input.before(box);box.append(input);
const list=document.createElement('ul');
list.className='combo-list';list.hidden=true;list.setAttribute('role','listbox');
box.append(list);
input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
const basePlaceholder=input.placeholder||'';
let chips=[],shown=[],active=0,generation=0,timer,navigated=false;
const changed=()=>{if(onChange)onChange()};
const same=(a,b)=>a.toLowerCase()===b.toLowerCase();
function drawChips(){
for(const chip of chips){
if(chip.node)continue;
const node=document.createElement('span');node.className='chip';
const text=document.createElement('span');text.className='chip-label';text.textContent=chip.label;
const remove=document.createElement('button');remove.type='button';remove.className='chip-remove';remove.textContent='×';
remove.setAttribute('aria-label','Remove '+chip.label);
remove.addEventListener('mousedown',event=>{if(event.preventDefault)event.preventDefault()});
remove.addEventListener('click',()=>removeChip(chip.value));
node.append(text,remove);chip.node=node;chip.text=text;chip.button=remove;
input.before(node);
}
input.placeholder=chips.length?'':basePlaceholder;
}
function addChip(item){
if(!item||typeof item.value!=='string'||!item.value||chips.some(chip=>same(chip.value,item.value)))return false;
chips.push({value:item.value,label:item.label||item.value});drawChips();return true;
}
function removeChip(value){
const at=chips.findIndex(chip=>same(chip.value,value));if(at<0)return;
const [chip]=chips.splice(at,1);if(chip.node&&chip.node.remove)chip.node.remove();
input.placeholder=chips.length?'':basePlaceholder;changed();
}
function close(){generation++;clearTimeout(timer);shown=[];list.hidden=true;list.replaceChildren();input.setAttribute('aria-expanded','false')}
function render(query){
list.replaceChildren();
shown.forEach(({candidate,match},index)=>{
const item=document.createElement('li');item.setAttribute('role','option');item.className=index===active?'active':'';item.setAttribute('aria-selected',String(index===active));
const marked=new Set(match.indices);
let plain=null;
[...candidate.label].forEach((char,at)=>{
if(marked.has(at)){plain=null;const mark=document.createElement('mark');mark.textContent=char;item.append(mark)}
else if(plain){plain.textContent+=char}
else{plain=document.createElement('span');plain.textContent=char;item.append(plain)}
});
item.addEventListener('mousedown',event=>{if(event.preventDefault)event.preventDefault();pick(index)});
list.append(item);
});
if(!shown.length){const hint=emptyText(query);if(hint){const item=document.createElement('li');item.className='empty';item.textContent=hint;list.append(item)}}
list.hidden=!shown.length&&!list.children.length;
input.setAttribute('aria-expanded',String(!list.hidden&&shown.length>0));
}
function refresh(){
const token=input.value.trim(),run=++generation;
clearTimeout(timer);
const run_=async()=>{
let candidates=[];try{candidates=await source(token)}catch{candidates=[]}
if(run!==generation)return;
shown=rankCandidates(token,candidates.filter(candidate=>!chips.some(chip=>same(chip.value,candidate.value))),limit);
active=0;render(token);
};
if(delay>0)timer=setTimeout(run_,delay);else run_();
}
function pick(index){
const choice=shown[index];if(!choice)return;
addChip(choice.candidate);input.value='';close();navigated=false;changed();
}
// Turn typed text into a chip: a known candidate, or the raw text when the field accepts free values.
function commitText(text){
const token=text.trim();if(!token)return true;
const hit=resolve(token);
if(hit)return addChip(hit)||true;
if(allowRaw)return addChip({value:token,label:token})||true;
return false;
}
function commitPending(){
const token=input.value.trim();if(!token)return;
if(commitText(token))input.value='';
changed();
}
function move(step){
if(!shown.length)return;
active=(active+step+shown.length)%shown.length;navigated=true;
[...list.children].forEach((item,index)=>{item.className=index===active?'active':'';item.setAttribute('aria-selected',String(index===active));if(index===active&&item.scrollIntoView)item.scrollIntoView({block:'nearest'})});
}
input.addEventListener('focus',refresh);
input.addEventListener('click',refresh);
input.addEventListener('input',()=>{
navigated=false;
if(COMBO_SEPARATOR.test(input.value)){
const parts=input.value.split(COMBO_SEPARATOR),rest=parts.pop().trimStart(),kept=parts.map(part=>part.trim()).filter(part=>part&&!commitText(part));
input.value=[...kept,rest].join(', ').replace(/^[\s,]+/,'');changed();
}
refresh();
});
input.addEventListener('blur',()=>{commitPending();close()});
input.addEventListener('keydown',event=>{
const open=!list.hidden&&shown.length>0,token=input.value.trim();
if((event.ctrlKey||event.metaKey)&&(event.key===' '||event.code==='Space')){event.preventDefault();if(open)pick(active);else{navigated=false;refresh()}}
else if(event.key==='ArrowDown'){if(open){event.preventDefault();move(1)}else refresh()}
else if(event.key==='ArrowUp'){if(open){event.preventDefault();move(-1)}}
else if(event.key==='Tab'&&!event.shiftKey&&open&&(token||navigated)){event.preventDefault();pick(active)}
else if(event.key==='Enter'&&open&&navigated){event.preventDefault();pick(active)}
else if(event.key==='Enter'&&token){event.preventDefault();commitPending();close()}
else if(event.key==='Backspace'&&!input.value&&chips.length){removeChip(chips.at(-1).value);refresh()}
else if(event.key==='Escape'&&!list.hidden){event.preventDefault();close()}
});
return {
refresh,close,
get values(){return chips.map(chip=>({value:chip.value,label:chip.label}))},
get pending(){return input.value.trim()},
// Programmatic updates (restoring saved values, adding names once Jira resolves them) do not call onChange.
set(items){for(const chip of chips)if(chip.node&&chip.node.remove)chip.node.remove();chips=[];for(const item of items)addChip(item);drawChips()},
relabel(value,label){const chip=chips.find(chip=>same(chip.value,value));if(chip){chip.label=label;if(chip.text)chip.text.textContent=label;if(chip.button)chip.button.setAttribute('aria-label','Remove '+label)}},
remove:removeChip,
};
}
