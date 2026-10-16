
// Fuzzy "skim"-style candidates for a comma-separated text field. Tab (or Enter after arrow keys) completes the current token.
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
const COMBO_SEPARATORS=[',','，','、',';'];
function comboParts(value){
const cut=Math.max(...COMBO_SEPARATORS.map(char=>value.lastIndexOf(char)));
const head=value.slice(0,cut+1);
return {head,token:value.slice(cut+1).trim(),chosen:new Set(head.split(/[,，、;]/).map(name=>name.trim().toLowerCase()).filter(Boolean))};
}
function attachCombo(input,{source,onPick,limit=8,delay=0,emptyText=()=>''}){
const list=document.createElement('ul');
list.className='combo-list';list.hidden=true;list.setAttribute('role','listbox');
input.parentElement.append(list);
input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');
let shown=[],active=0,generation=0,timer,navigated=false;
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
const {token,chosen}=comboParts(input.value),run=++generation;
clearTimeout(timer);
const run_=async()=>{
let candidates=[];try{candidates=await source(token)}catch{candidates=[]}
if(run!==generation)return;
shown=rankCandidates(token,candidates.filter(candidate=>!chosen.has(candidate.value.toLowerCase())),limit);
active=0;render(token);
};
if(delay>0)timer=setTimeout(run_,delay);else run_();
}
function pick(index){
const choice=shown[index];if(!choice)return;
const {head}=comboParts(input.value);
input.value=(head?head.replace(/\s*$/,' '):'')+choice.candidate.value+', ';
close();navigated=false;
if(onPick)onPick(choice.candidate);
}
function move(step){
if(!shown.length)return;
active=(active+step+shown.length)%shown.length;navigated=true;
[...list.children].forEach((item,index)=>{item.className=index===active?'active':'';item.setAttribute('aria-selected',String(index===active));if(index===active&&item.scrollIntoView)item.scrollIntoView({block:'nearest'})});
}
input.addEventListener('focus',refresh);
input.addEventListener('click',refresh);
input.addEventListener('input',()=>{navigated=false;refresh()});
input.addEventListener('blur',close);
input.addEventListener('keydown',event=>{
const open=!list.hidden&&shown.length>0;
if((event.ctrlKey||event.metaKey)&&(event.key===' '||event.code==='Space')){event.preventDefault();navigated=false;refresh()}
else if(event.key==='ArrowDown'){if(open){event.preventDefault();move(1)}else refresh()}
else if(event.key==='ArrowUp'){if(open){event.preventDefault();move(-1)}}
else if(event.key==='Tab'&&!event.shiftKey&&open&&(comboParts(input.value).token||navigated)){event.preventDefault();pick(active)}
else if(event.key==='Enter'&&open&&navigated){event.preventDefault();pick(active)}
else if(event.key==='Escape'&&!list.hidden){event.preventDefault();close()}
});
return {refresh,close};
}
