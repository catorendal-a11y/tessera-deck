// Editor part 1 of 3 (core.js, app.js, dialogs.js share one global scope): data, state, undo, labels and gauges.
'use strict';
const $ = s => document.querySelector(s);
const clone = value => structuredClone(value);
const icons = {ok:'✓',close:'✕',settings:'⚙',home:'⌂',folder:'▱',download:'↓',refresh:'↻',play:'▶',pause:'Ⅱ',stop:'■',plus:'＋',minus:'−',loop:'↺',list:'☷',upload:'↑',bolt:'ϟ',bell:'♧',wifi:'◉',trash:'⌫',edit:'✎'};
const iconNames = {ok:'Check',close:'Cross',settings:'Settings',home:'Home',folder:'Folder',download:'Download',refresh:'Refresh',play:'Play',pause:'Pause',stop:'Stop',plus:'Plus',minus:'Minus',loop:'Repeat',list:'List',upload:'Upload',bolt:'Bolt',bell:'Alert',wifi:'Network',trash:'Delete',edit:'Edit'};
const kinds = {
  hotkey:{name:'Hotkey',icon:'bolt',field:'keys',label:'Key combination',placeholder:'ctrl+shift+b',group:'On the computer'},
  open:{name:'Open program / file',icon:'folder',field:'target',label:'Program, file or web address',placeholder:'Choose a program or paste a path',group:'On the computer'},
  text:{name:'Type text',icon:'edit',field:'text',label:'Text to type',placeholder:'Type the text here …',group:'On the computer'},
  folder:{name:'Open folder',icon:'folder',field:'page',label:'Folder',group:'Navigation'},
  back:{name:'Back',icon:'home',field:null,label:'Back to the previous folder',group:'Navigation'},
  page:{name:'Switch page',icon:'folder',field:'page',label:'Go to page',group:'Navigation'},
  profile:{name:'Switch profile',icon:'list',field:'profile',label:'Go to profile',group:'Navigation'},
  profile_lock:{name:'Lock profile',icon:'settings',field:null,label:'Lock or unlock automatic profile switching',group:'Navigation'},
  delay:{name:'Wait',icon:'pause',field:'ms',label:'Delay (milliseconds)',placeholder:'500',group:'More actions'},
  shell:{name:'Run command',icon:'settings',field:'command',label:'Command',placeholder:'The command runs when the key is pressed',group:'Advanced'},
  http:{name:'HTTP request',icon:'wifi',field:'url',label:'Address',placeholder:'https://…',group:'Advanced'},
  press:{name:'Trigger another key',icon:'loop',field:'id',label:'Key number (1–18)',group:'Advanced'},
  audio:{name:'Mute / unmute audio',icon:'settings',field:'target',label:'Device',group:'On the computer'},
  counter:{name:'Counter',icon:'plus',field:'name',label:'Counter name',placeholder:'for example laps',group:'On the computer'},
  mouse:{name:'Mouse',icon:'settings',field:'op',label:'Mouse operation',group:'On the computer'},
  screen:{name:'Switch screen',icon:'home',field:'show',label:'Show on the panel',group:'More actions'},
  timer:{name:'Timer',icon:'pause',field:'name',label:'Timer name',placeholder:'for example tea',group:'On the computer'},
  set:{name:'Set variable',icon:'edit',field:'variable',label:'Variable name',group:'Advanced'},
  state:{name:'Set key state',icon:'loop',field:'button',label:'Key number (1–18)',group:'Advanced'},
  home:{name:'Go home',icon:'home',field:null,label:'Go to the first page of the default profile',group:'Navigation'},
};
// Sensors the host provides, with the ranges and thresholds of the bundled status page.
const gaugeSensors={
  fps:['FPS (HWiNFO PresentMon)',{max:240,unit:'fps'}],
  cpu_load:['CPU load',{max:100,unit:'%',warn:85,critical:97}],cpu_temp:['CPU temperature',{max:100,unit:'C',warn:80,critical:90}],
  cpu_power:['CPU power',{max:170,unit:'W',warn:130,critical:160}],cpu_clock:['CPU clock',{max:5500,fmt:'ghz'}],
  ram:['RAM',{max:100,unit:'%',warn:85,critical:95}],disk:['Disk',{max:100,unit:'%',warn:90,critical:97}],
  gpu_load:['GPU load',{max:100,unit:'%'}],vram_used_gb:['VRAM',{percent_key:'vram',max:100,fmt:'gb',warn:85,critical:95}],
  gpu_temp:['GPU temperature',{max:110,unit:'C',warn:85,critical:100}],gpu_power:['GPU power',{max:350,unit:'W',warn:320,critical:360}],
  gpu_clock:['GPU clock',{max:2600,fmt:'ghz'}],gpu_fan:['GPU fan',{max:3000,unit:'rpm'}],
  net_down:['Download',{max:125000000,fmt:'rate',scale:'log'}],net_up:['Upload',{max:125000000,fmt:'rate',scale:'log'}],
  uptime:['Uptime',{max:604800,fmt:'uptime'}],sensors:['Sensor source',{max:1,fmt:'live'}]
};
const presets = [
  {name:'Mute / unmute',icon:'minus',keys:'volumemute'}, {name:'Volume down',icon:'minus',keys:'volumedown'},
  {name:'Volume up',icon:'plus',keys:'volumeup'}, {name:'Play / pause',icon:'play',keys:'playpause'},
  {name:'Next track',icon:'refresh',keys:'medianext'}, {name:'Previous track',icon:'loop',keys:'mediaprev'},
  {name:'Copy',icon:'list',keys:'ctrl+c'}, {name:'Paste',icon:'download',keys:'ctrl+v'},
  {name:'Screenshot',icon:'bolt',keys:'win+shift+s'}
];
let config, revision, profile, page, selected=1, history=[], future=[], clipboard=null;
let dirty=false, saving=false, saveInFlight=null, conflicted=false, version=0, saveTimer, toastTimer, recording=null, dashboard={};
let drag=null, suppressClick=false, editState=0;
let iconPack=null, packIcons=new Map(), iconPage=0, iconPreferences={favorites:[],recent:[]};
let actionCatalog={packs:[],templates:[]};
let installedPrograms=[];
let lastActionAt=0;
let dialogReturnFocus=null,iconReturnFocus=null,keyMenuReturnFocus=null;
const iconPageSize=72;
const iconGroups={
  'Audio and video':/audio|sound|volume|microphone|\bmic\b|music|speaker|headphone|video|camera|film|podcast|radio|play|pause/,
  'Files and folders':/file|folder|document|archive|clipboard|save|download|upload/,
  'Development':/code|terminal|git|bug|database|braces|brackets|regex|binary|cpu/,
  'Network':/network|wifi|ethernet|router|cloud|server|bluetooth|internet|globe|signal/,
  'Home and devices':/house|home|light|lamp|bulb|plug|power|battery|monitor|keyboard|mouse|printer|phone|tablet|laptop|computer/,
  'Games':/game|joystick|dice|sword|trophy|medal|target|crosshair|puzzle/,
  'Work':/calendar|mail|briefcase|chart|presentation|clock|timer|alarm|notebook|contact|users|user|meeting/,
  'Arrows and navigation':/arrow|chevron|navigation|move|map|route|compass|menu|panel|layout/
};
const searchAliases={mic:['microphone'],sound:['audio','volume','speaker'],music:['headphones','audio'],screen:['monitor','display'],wifi:['network','ethernet'],light:['lamp','bulb'],email:['mail','inbox'],time:['clock','timer'],delete:['trash'],power:['plug','battery'],game:['joystick','dice'],settings:['sliders'],code:['terminal','braces'],tool:['wrench','hammer'],work:['briefcase','calendar','chart']};

function iconVisual(id,color,cls='key-symbol') {
  if(id?.startsWith('im:'))return element('img',{class:cls,src:'/api/image/'+id,alt:'',draggable:'false'});
  const item=packIcons.get(id);
  if(!item)return text('span',icons[id]||icons.ok,cls);
  const tint=/^#[0-9a-f]{6}$/i.test(color||'')?color:'#92edba';
  const svg=item.svg.replaceAll('currentColor',tint);
  return element('img',{class:cls,src:'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg),alt:'',loading:'lazy',draggable:'false'});
}
async function loadIconPack() {
  if(iconPack)return;
  const value=await api('icons');iconPack=value;iconPreferences=value.preferences||iconPreferences;
  packIcons=new Map(value.icons.map(item=>{
    item.search=[item.name,...item.aliases,...item.tags].join(' ').replaceAll('-',' ').toLowerCase();
    item.groups=Object.entries(iconGroups).filter(([,pattern])=>pattern.test(item.search)).map(([name])=>name);
    return [item.id,item];
  }));
  options($('#icon-category'),['All icons','Favorites','Recently used',...Object.keys(iconGroups)],'All icons');
  $('#icon-pack-info').textContent=`${value.count.toLocaleString('en-US')} unique icons · ${value.name} ${value.version} · No internet connection needed`;
  renderGrid();renderInspector();
}
function saveIconPreferences() {api('icon-preferences',iconPreferences).catch(error=>toast('Icon choice kept, but the favorites list could not be saved: '+error.message));}
let iconPick = null;  // when set, a chosen icon goes here instead of to the selected key
document.getElementById('icon-dialog')?.addEventListener('close',()=>{iconPick=null;});  // closed without a choice
async function openIcons() {
  try {
    await loadIconPack();iconReturnFocus=document.activeElement;iconPage=0;$('#icon-search').value='';renderIconResults();$('#icon-dialog').showModal();$('#icon-search').focus();
  }catch(error){showError(error);}
}
function renderIconResults() {
  if(!iconPack)return;
  const query=$('#icon-search').value.trim().toLowerCase().replaceAll('-',' '),group=$('#icon-category').value;
  const terms=query.split(/\s+/).filter(Boolean).map(word=>[word,...(searchAliases[word]||[])]);
  let list=iconPack.icons.filter(item=>(group==='All icons'||group==='Favorites'&&iconPreferences.favorites.includes(item.id)||group==='Recently used'&&iconPreferences.recent.includes(item.id)||item.groups.includes(group))&&
    (!query||terms.every(alternatives=>alternatives.some(word=>word.length<=3?item.search.split(' ').includes(word):item.search.includes(word)))));
  if(group==='Recently used')list.sort((a,b)=>iconPreferences.recent.indexOf(a.id)-iconPreferences.recent.indexOf(b.id));
  else list.sort((a,b)=>a.name.localeCompare(b.name));
  const pages=Math.max(1,Math.ceil(list.length/iconPageSize));iconPage=Math.min(iconPage,pages-1);
  const shown=list.slice(iconPage*iconPageSize,(iconPage+1)*iconPageSize),color=current()?.color||'#35D07F';
  $('#icon-results').replaceChildren(...shown.map(item=>{
    const selected=current()?.icon===item.id,favorite=iconPreferences.favorites.includes(item.id);
    const choose=button('',()=>{
      if(iconPick){const pick=iconPick;iconPick=null;pick(item.id);}else mutate(()=>{if(current())appearance().icon=item.id;});
      iconPreferences.recent=[item.id,...iconPreferences.recent.filter(id=>id!==item.id)].slice(0,24);saveIconPreferences();$('#icon-dialog').close();
    },'catalog-choice'+(selected?' selected':''),item.name);
    choose.setAttribute('aria-label','Choose icon '+item.name);choose.setAttribute('aria-pressed',selected);
    choose.append(iconVisual(item.id,color,'catalog-symbol'),text('span',item.name,'catalog-name'));
    const star=button(favorite?'★':'☆',()=>{
      if(favorite)iconPreferences.favorites=iconPreferences.favorites.filter(id=>id!==item.id);
      else if(iconPreferences.favorites.length<512)iconPreferences.favorites.push(item.id);
      else return toast('The favorites list is full. Remove an icon first.');
      saveIconPreferences();renderIconResults();
    },'catalog-star'+(favorite?' favorite':''),favorite?'Remove favorite':'Add to favorites');
    star.setAttribute('aria-label',(favorite?'Remove favorite ':'Favorite ')+item.name);star.setAttribute('aria-pressed',favorite);
    return element('div',{class:'catalog-item'},choose,star);
  }));
  if(!shown.length)$('#icon-results').append(text('p',group==='Favorites'?'Press ☆ on an icon to add it to favorites.':'No matches. Try another word or category.','hint icon-empty'));
  $('#icon-count').textContent=list.length?`${iconPage*iconPageSize+1}–${Math.min(list.length,(iconPage+1)*iconPageSize)} of ${list.length.toLocaleString('en-US')} icons`:'0 icons';
  $('#icons-prev').disabled=iconPage===0;$('#icons-next').disabled=iconPage>=pages-1;
  $('#icon-results').scrollTop=0;
}

const BOOLEAN_ATTRIBUTES=new Set(['disabled','hidden','checked','selected','required','readonly','open','multiple']);
function element(tag, attrs={}, ...children) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)) {
    if(key==='text') node.textContent=value;
    else if(key==='class') node.className=value;
    else if(key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if(BOOLEAN_ATTRIBUTES.has(key)&&typeof value==='boolean'){if(value)node.setAttribute(key,'');}  // disabled:false must not disable
    else if(value!==undefined && value!==null) node.setAttribute(key,String(value));
  }
  for(const child of children.flat()) if(child) node.append(child);
  return node;
}
const button=(text,fn,cls='quiet',title) => element('button',{text,class:cls,onclick:fn,type:'button',title});
const text=(tag,value,cls) => element(tag,{text:value,class:cls||''});
function toast(message,undoable=false) {const host=document.querySelector('dialog:modal')||document.body;if($('#toast').parentNode!==host){host.append($('#toast'));if(host!==document.body)host.addEventListener('close',()=>document.body.append($('#toast')),{once:true});}
  $('#toast').textContent=message;
  if(undoable)$('#toast').append(button('Undo',()=>{undo();$('#toast').hidden=true;},'toast-undo'));$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4800);}
async function api(path, data) {
  const response=await fetch('/api/'+path, {method:data===undefined?'GET':'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Deck-Request':'1'},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();
  if(!response.ok) {const error=new Error(result.error||'The operation failed');error.status=response.status;throw error;}
  return result;
}
function buttons() {return config.profiles[profile].pages[page];}
function profileButtons(item) {return [...Object.values(item.pages).flat(),...(item.pinned||[])];}
/* Rail shortcuts that run steps hold actions too, so renames and deletes reach them like keys. */
function railSteps() {return (config.panel?.shortcuts||[]).filter(s=>s.type==='actions');}
function rewriteActions(items,transform) {
  const rewrite=list=>list.flatMap(action=>{const changed=transform(action);return changed?[changed]:[];});
  for(const b of items){for(const holder of [b,...(b.states||[])])holder.actions=rewrite(holder.actions||[]);
    for(const key of ['hold_actions','double_actions'])if(b[key]){b[key]=rewrite(b[key]);if(!b[key].length)delete b[key];}}
}
function visibleButtons() {const values=new Map(buttons().map(b=>[b.id,b]));for(const b of config.profiles[profile].pinned||[])values.set(b.id,b);return [...values.values()];}
function current() {return visibleButtons().find(b=>b.id===selected);}
function owner(id=selected) {const pins=config.profiles[profile].pinned||[];return pins.some(b=>b.id===id)?pins:buttons();}
function appearance(b=current()) {return b?.states?.[editState]||b;}
/* Which action list of the key the steps below edit: a normal press, a long press or a double press. */
let editList='actions';
const TRIGGERS=[['actions','Pressed'],['hold_actions','Held'],['double_actions','Double-press']];
function activeActions() {const b=current();if(editList!=='actions')return b[editList]||[];return b.states?b.states[Math.min(editState,b.states.length-1)].actions:b.actions;}
function togglePin() {mutate(()=>{const b=current(),list=owner(),p=config.profiles[profile];list.splice(list.indexOf(b),1);p.pinned??=[];if(list===p.pinned){const at=buttons().findIndex(v=>v.id===b.id);if(at>=0)buttons().splice(at,1);buttons().push(b);}else p.pinned.push(b);});}
function uniqueName(base,names) {let name=`${base} copy`,number=2;while(names.includes(name))name=`${base} copy ${number++}`;return name;}
function clearButton() {if(!current())return;mutate(()=>{const list=owner(),at=list.findIndex(x=>x.id===selected);if(at>=0)list.splice(at,1);});}
function duplicateButton() {
  const source=current(),slot=Array.from({length:18},(_,i)=>i+1).find(id=>spanFits(id,source?.span||1));
  if(!source)return;if(!slot)return toast('This page has no free slots.');
  mutate(()=>{buttons().push({...clone(source),id:slot});selected=slot;editState=0;});
  toast(`The key was duplicated to slot ${slot}.`);
}
function duplicateProfile() {
  const name=uniqueName(profile,Object.keys(config.profiles));
  mutate(()=>{config.profiles[name]=clone(config.profiles[profile]);profile=name;page=Object.keys(config.profiles[name].pages)[0];selected=1;editState=0;});
  renderAll();toast(`Profile “${name}” was created.`);
}
function duplicatePage() {
  const pages=config.profiles[profile].pages,name=uniqueName(page,Object.keys(pages));
  mutate(()=>{pages[name]=clone(pages[page]);page=name;selected=1;editState=0;});
  renderAll();toast(`Page “${name}” was created.`);
}
async function uploadImage(file,id=selected) {if(!file)return;if(file.size>8*1024*1024)throw new Error('Use an image of at most 8 MB');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let at=0;at<bytes.length;at+=16384)binary+=String.fromCharCode(...bytes.subarray(at,at+16384));const result=await api('image',{data:btoa(binary)});mutate(()=>{selected=id;if(!current())buttons().push({id,label:file.name.replace(/\.[^.]+$/,''),icon:'ok',color:'#35D07F',actions:[]});appearance().icon=result.id;});if(result.sampled)toast('The animation was reduced to 12 frames for the panel.');}

function setSaveState(message,note='Changes are saved automatically.') {$('#save-state').textContent=message;$('#save-note').textContent=note;}
function draftError() {
  for(const item of Object.values(config.profiles)) for(const b of profileButtons(item)) {
    if(!b.label?.trim()) return 'Give the key a name';
    if((b.states||[]).some(state=>state.label!==undefined&&!String(state.label).trim()))return 'Give every state of the toggle key a name';
    for(const holder of [b,...(b.states||[])]) for(const a of [...(holder.actions||[]),...(holder===b?[...(b.hold_actions||[]),...(b.double_actions||[])]:[])]) {
      const kind=kinds[a.type];
      if(!kind) return 'Unknown action';
      if(kind.field && a.type!=='text' && (a[kind.field]===undefined || String(a[kind.field]).trim()==='')) return `${b.label}: fill in ${kind.label.toLowerCase()}`;
    }
  }
  return '';
}
// Typing in one field becomes a single undo step; a pause or another edit starts a new one.
let lastEdit={key:null,at:0};
function remember(key=null) {
  const now=Date.now();
  if(key&&key===lastEdit.key&&now-lastEdit.at<1500){lastEdit.at=now;future=[];return;}
  lastEdit={key,at:now};history.push(clone(config));if(history.length>60)history.shift();future=[];
}
const editKey=(...parts)=>[profile,page,selected,editState,...parts].join('\u0000');
function changed() {
  dirty=true;version++;clearTimeout(saveTimer);renderGrid();updateHistory();
  const error=draftError();if(conflicted)setSaveState('Not saved · press Reload','The configuration was changed in another window.');else setSaveState(error?'Draft · '+error:'Saving …',error?'Fill in the field, or undo the change.':'The change is sent automatically to the active page.');
  if(!error&&!conflicted)saveTimer=setTimeout(()=>save().catch(showError),650);
}
function mutate(fn,refresh=true,key=null) {remember(key);fn();changed();if(refresh)renderInspector();}
function showError(error) {toast(error.message);if(error.status===409){conflicted=true;$('#reload').hidden=false;}}
async function save() {
  clearTimeout(saveTimer);
  if(saveInFlight){await saveInFlight;if(dirty)return save();return;}
  if(!dirty) return;
  const invalid=draftError();if(invalid)throw new Error(invalid);
  if(conflicted)throw new Error('Reload the configuration to resolve the conflict.');
  saving=true;const sentVersion=version;
  try {
    saveInFlight=api('config',{config:clone(config),revision});
    const result=await saveInFlight;revision=result.revision;
    if(version===sentVersion){dirty=false;const same=dashboard.device?.profile===profile&&dashboard.device?.page===page;
      setSaveState('✓ Saved on the PC',dashboard.device?.connected?(same?'This page is up to date on the panel.':(dashboard.device.profile?`The panel shows ${dashboard.device.profile} / ${dashboard.device.page}. Turn on Mirror on panel to show this page.`:'Waiting for the panel to report which page it shows.')):'Connect the panel and start the host to synchronize.');}
  } catch(error){setSaveState('Not saved · '+error.message);throw error;} finally {saving=false;saveInFlight=null;}
  if(dirty)saveTimer=setTimeout(()=>save().catch(showError),200);
}
function updateHistory() {$('#undo').disabled=!history.length;$('#redo').disabled=!future.length;}
function undo(redo=false) {const source=redo?future:history,target=redo?history:future;if(!source.length)return;lastEdit={key:null,at:0};target.push(clone(config));config=source.pop();ensureSelection();changed();renderAll();}
function ensureSelection() {
  if(!config.profiles[profile])profile=config.default_profile||Object.keys(config.profiles)[0];
  if(!config.profiles[profile].pages[page])page=Object.keys(config.profiles[profile].pages)[0];
  const selectedButton=current();if(!selectedButton?.states||editState>=selectedButton.states.length)editState=0;
}
function options(select,values,value) {select.replaceChildren(...values.map(v=>{const pair=Array.isArray(v)?v:[v,v];return element('option',{value:pair[0],text:pair[1]});}));select.value=value;}
/* A key of `span` slots starting at `id` must sit on one row, inside the 18 slots, on slots no other key (apart from `skip`) uses. */
function spanFits(id,span,skip=[]) {
  if(id<1||id+span-1>18||Math.floor((id-1)/6)!==Math.floor((id+span-2)/6))return false;
  return !visibleButtons().some(b=>!skip.includes(b)&&b.id<id+span&&id<b.id+(b.span||1));
}
function moveSlot(source,target) {
  if(source===target)return;
  const from=visibleButtons().find(b=>b.id===source),to=visibleButtons().find(b=>b.id===target);if(!from)return;
  const fromSpan=from.span||1,toSpan=to?.span||1,skip=[from,to];
  const separate=target+fromSpan-1<source||target>source+toSpan-1;  // the two keys do not overlap after the swap
  if(!spanFits(target,fromSpan,skip)||(to&&!spanFits(source,toSpan,skip))||(to&&!separate))return toast('A wide key needs free slots on one row: it does not fit there.');
  mutate(()=>{from.id=target;if(to)to.id=source;selected=target;});
}
function renderAll() {ensureSelection();options($('#profile'),Object.keys(config.profiles),profile);renderPages();renderGrid();renderInspector();updateHistory();renderStatus();}
function renderPages() {
  $('#page-list').replaceChildren(...Object.keys(config.profiles[profile].pages).map(name=>{
    const item=button(name,()=>{page=name;selected=1;editState=0;renderAll();syncPanel();},'page-chip'+(page===name?' active':''));
    item.setAttribute('aria-current',page===name?'page':'false');return item;
  }));
}
const DEVICE={cell:150,gap:17,x:19,y:17};
function tileGeometry(b) {
  const title=b?.title||{},position=title.position||'bottom',size=title.size||16;
  const px=title.bold&&size===16?20:size;
  const labelTop=position==='top'?10:position==='middle'?Math.round((DEVICE.cell-px)/2):DEVICE.cell-px-17;
  return {px,labelTop,hidden:position==='hidden',symbolTop:position==='top'};
}
// The host cuts labels to 24 UTF-8 bytes without splitting a character; mirror it.
const LABEL_BYTES=24;
function panelLabel(value) {
  const bytes=new TextEncoder().encode(value);if(bytes.length<=LABEL_BYTES)return value;
  let end=LABEL_BYTES;while(end>0&&(bytes[end]&0xC0)===0x80)end--;
  return new TextDecoder().decode(bytes.subarray(0,end));
}
// Same variables as the host's substitute(): unset $(var:…) renders empty, unknown tokens stay as typed.
function resolveLabel(value) {return panelLabel(expandLabel(value));}
function expandLabel(value) {
  const now=new Date(),two=n=>String(n).padStart(2,'0');
  const text=String(value||'').replace(/[$][(]([a-z_-]+)(?::([A-Za-z0-9_.-]+))?[)]/g,(match,kind,name)=>{
    const live=dashboard.variables?.[name?`${kind}:${name}`:kind];
    if(live!==undefined&&['pc','counter','timer','timer-state'].includes(kind))return String(live);
    if(kind==='profile_lock'&&!name)return String(live??'AUTO');
    if(kind==='agent')return dashboard.agents?.[name]?'ON':'OFF';
    if(kind==='profile'&&!name)return profile;if(kind==='page'&&!name)return page;
    if(kind==='time'&&!name)return `${two(now.getHours())}:${two(now.getMinutes())}`;
    if(kind==='date'&&!name)return `${two(now.getDate())}.${two(now.getMonth()+1)}`;
    if(kind==='var'&&name)return String(dashboard.vars?.[name]??'');
    if(kind==='stat'&&name)return String(dashboard.stats?.[name]??'--');
    return match;});
  return text.replace(/[\u0000-\u001f]/g,' ');
}
/* The icon is the gauge: a dim copy behind, the bright copy clipped to the filled part from the bottom, plus a badge for what is measured. */
function gaugeIcon(b,live) {
  const color=live?.color||b.color||'#35D07F',p=Math.max(0,Math.min(100,live?live.p:0));
  const dim=iconVisual(b.icon,color,'gauge-icon dim'),lit=iconVisual(b.icon,color,'gauge-icon');
  lit.style.clipPath=`inset(${(55-50*p/100)/60*100}% 0 0 0)`;
  const out=[dim,lit];
  if(b.gauge?.badge){const disc=element('span',{class:'gauge-badge'});disc.style.background=color;disc.append(iconVisual(b.gauge.badge,'#0d1417','gauge-badge-icon'));out.push(disc);}
  return out;
}
function deviceShowsSelection() {const d=dashboard.device;return !!d?.connected&&d.profile===profile&&d.page===page;}
function renderGrid() {
  const grid=$('#deck-grid');const focused=document.activeElement?.dataset.slot;
  const live=deviceShowsSelection()?(dashboard.device?.gauges||{}):{};
  const shown=[...grid.children];
  const covered=new Set();for(const wide of visibleButtons())for(let extra=1;extra<(wide.span||1);extra++)covered.add(wide.id+extra);
  const next=Array.from({length:18},(_,index)=>{
    const id=index+1,base=visibleButtons().find(b=>b.id===id),b=base&&{...base,...(id===selected?appearance(base):base.states?.[0]||{})};
    const tile=element('button',{class:'deck-key'+(!b?' empty':'')+(id===selected?' selected':''),type:'button',draggable:'false',
      'data-slot':id,'aria-label':`Key ${id}: ${b?.label||'Empty slot'}`,'aria-pressed':id===selected,
      onclick:()=>{selected=id;editState=0;renderGrid();renderInspector();}});
    tile.style.left=`${DEVICE.x+(index%6)*(DEVICE.cell+DEVICE.gap)}px`;
    tile.style.top=`${DEVICE.y+Math.floor(index/6)*(DEVICE.cell+DEVICE.gap)}px`;
    tile.style.setProperty('--key-color',b?.color||'#92edba');
    if(b?.span>1){tile.classList.add('wide');tile.style.width=`${b.span*DEVICE.cell+(b.span-1)*DEVICE.gap}px`;tile.style.zIndex='2';}
    if(covered.has(id)){tile.style.visibility='hidden';tile.tabIndex=-1;tile.style.pointerEvents='none';}
    const look={...(b?config.theme:{})};
    for(const key of ['bg','text_color','border'])if(b?.[key])look[key]=b[key];
    if(look.bg)tile.style.background=look.bg;
    if(look.border){tile.style.borderColor=look.border;tile.style.borderWidth='3px';}
    if(look.text_color)tile.style.setProperty('--key-text',look.text_color);
    tile.append(text('span',String(id),'slot-number'));
    if(!b)tile.append(text('span','+','empty-plus'));
    else {
      const geometry=tileGeometry(b);
      if(b.gauge) {
        const shown=live[id]?.t||'--',number=/^[\d.,]*/.exec(shown)[0],unit=number?shown.slice(number.length):'';
        const value=text('span',number||shown,'gauge-value');value.style.color=live[id]?.color||b.color||'#35D07F';if(unit)value.append(text('small',unit,'gauge-unit'));
        tile.append(...gaugeIcon(b,live[id]),value);
      } else {
        const symbol=iconVisual(b.icon,b.color,'key-symbol');
        if(b.icon?.startsWith('im:'))symbol.classList.add('symbol-image');
        if(geometry.symbolTop)symbol.classList.add('symbol-top');
        tile.append(symbol);
      }
      const label=text('span',resolveLabel(b.label),'key-label');
      label.style.top=geometry.labelTop+'px';label.style.fontSize=geometry.px+'px';
      if(b.title?.bold)label.style.fontWeight='700';label.hidden=geometry.hidden;tile.append(label);
      tile.append(...gestureMarks(base));
      if(b.span>1&&b.live)tile.append(text('span',b.live==='media'?'♪ shows the music that plays':b.live.startsWith('timer:')?'◔ shows timer '+b.live.slice(6):'▣ '+(WIDGETS.find(w=>w.kind===b.live)?.name||b.live)+' widget','key-live'));
    }
    if(base&&config.profiles[profile].pinned?.includes(base))tile.append(text('span','◆','pin-badge'));
    tile.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
    tile.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();chooseImage(event.dataTransfer.files[0],id).catch(showError);}});
    tile.addEventListener('dragstart',event=>{if(!b)return event.preventDefault();event.dataTransfer.setData('application/x-deck-slot',String(id));event.dataTransfer.effectAllowed='move';});
    tile.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer.types).some(t=>['application/x-deck-action','application/x-deck-slot'].includes(t))){event.preventDefault();tile.classList.add('drag-over');event.dataTransfer.dropEffect=Array.from(event.dataTransfer.types).includes('application/x-deck-action')?'copy':'move';}});
    tile.addEventListener('dragleave',()=>tile.classList.remove('drag-over'));
    tile.addEventListener('drop',event=>{
      event.preventDefault();tile.classList.remove('drag-over');const source=Number(event.dataTransfer.getData('application/x-deck-slot'));
      if(source&&source!==id)moveSlot(source,id);
      else {const key=event.dataTransfer.getData('application/x-deck-action');if(key)addAction(key,id);}
    });
    tile.addEventListener('keydown',event=>{const delta={ArrowRight:1,ArrowLeft:-1,ArrowDown:6,ArrowUp:-6}[event.key];if(delta){event.preventDefault();let target=Math.max(1,Math.min(18,id+delta));const wide=visibleButtons().find(b=>b.id<target&&target<b.id+(b.span||1));if(wide)target=delta===1?wide.id+wide.span:wide.id;selected=target>18?id:target;renderGrid();renderInspector();$(`[data-slot="${selected}"]`).focus();}});
    if(b)tile.addEventListener('dblclick',event=>{event.preventDefault();renameButton(id);});
    return tile;
  });
  // Keys that look the same stay in place, so a live update does not interrupt a hover or a press on them.
  grid.replaceChildren(...next.map((tile,index)=>shown[index]?.isEqualNode(tile)?shown[index]:tile));
  if(focused)$(`[data-slot="${focused}"]`)?.focus();
}
/* The editor is designed for about 1450x900; larger windows scale everything up so the proportions stay the same. */
function applyZoom() {
  const zoom=Math.max(.72,Math.min(1.45,.85*innerHeight/990,.85*innerWidth/1450));  // 15% smaller than the design size
  document.documentElement.style.setProperty('--z',zoom.toFixed(3));
}
function fitDevice() {
  applyZoom();
  const frame=$('#device-frame'),screen=$('#device-screen');if(!frame||!screen)return;
  const scale=frame.clientWidth/1024;screen.style.transform=`scale(${scale})`;frame.style.height=`${600*scale}px`;
}
function tickClock() {const clock=$('#screen-clock');if(clock)clock.textContent=new Date().toTimeString().slice(0,5);}
function setupMoreMenu() {
  // Profile, Page, Panel and More: each named button opens its own menu, and only one is open at a time.
  const pairs=[...document.querySelectorAll('.more')].map(box=>[box.querySelector('[aria-haspopup=menu]'),box.querySelector('.more-menu')]);
  const close=()=>{for(const [toggle,menu] of pairs){menu.hidden=true;toggle.setAttribute('aria-expanded','false');}};
  // The buttons sit in the middle of the window: open each menu right under its button, and never past the edge.
  const place=(toggle,menu)=>{
    Object.assign(menu.style,{position:'fixed',top:'0px',left:'0px',right:'auto',bottom:'auto',maxHeight:''});
    const origin=menu.getBoundingClientRect(),scale=origin.width/menu.offsetWidth||1,button=toggle.getBoundingClientRect();
    const left=Math.max(16,Math.min(button.left,innerWidth-origin.width-16)),top=button.bottom+6;
    // fixed coordinates inside a zoomed part of the page are in its own units: undo the zoom and the origin
    menu.style.left=(left-origin.left)/scale+'px';menu.style.top=(top-origin.top)/scale+'px';
    menu.style.maxHeight=Math.max(220,(innerHeight-top-16)/scale)+'px';};
  for(const [toggle,menu] of pairs){
    toggle.onclick=event=>{event.stopPropagation();const open=menu.hidden;close();if(!open)return;
      menu.hidden=false;toggle.setAttribute('aria-expanded','true');place(toggle,menu);menu.querySelector('[role=menuitem]')?.focus();};
    menu.addEventListener('keydown',event=>{const items=[...menu.querySelectorAll('[role=menuitem]')],at=items.indexOf(document.activeElement);
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();items[(at+(event.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();}
      else if(event.key==='Escape'){close();toggle.focus();}});
    menu.addEventListener('click',event=>{if(event.target.closest('button'))close();});
  }
  document.addEventListener('click',event=>{if(!event.target.closest('.more'))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
}
async function syncPanel() {
  if(!$('#sync').checked||!dashboard.running)return;
  try{await api('command/activate',{profile,page});}catch(error){/* unsaved or unknown page: the panel keeps its page */}
}
let lastDevicePath='';
function followDevice() {
  const d=dashboard.device;if(!$('#sync').checked||!d?.connected||!d.profile||document.querySelector('dialog[open]'))return;
  const path=d.profile+'|'+d.page;if(path===lastDevicePath)return;lastDevicePath=path;
  if(config.profiles[d.profile]?.pages?.[d.page]&&(d.profile!==profile||d.page!==page)){profile=d.profile;page=d.page;selected=1;editState=0;renderAll();}
}
function actionTemplate(key) {
  if(key.startsWith('pack:')) {const pack=actionCatalog.packs[Number(key.split(':')[1])];if(!pack)return;return {label:pack.name,icon:pack.icon||'ok',color:pack.color||'#35D07F',actions:clone(pack.actions)};}
  if(key.startsWith('preset:')) {const preset=presets[Number(key.split(':')[1])];if(!preset)return;return {label:preset.name,icon:preset.icon,actions:[{type:'hotkey',keys:preset.keys}]};}
  const k=kinds[key];if(!k)return;
  const value={hotkey:'',text:'',open:'',folder:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,back:null,page:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,
    profile:Object.keys(config.profiles).find(p=>p!==profile)||profile,delay:500,shell:'',http:'',press:1,set:'',state:1,audio:'mic',counter:'counter',timer:'timer',mouse:'left',screen:'clock'}[key];
  const action={type:key,...(k.field?{[k.field]:value}:{}),...(key==='http'?{method:'GET'}:{}),...(key==='state'?{state:'next'}:{}),...(key==='audio'?{op:'toggle'}:{}),
    ...(key==='counter'?{op:'inc',step:1}:{}),...(key==='timer'?{op:'toggle',seconds:300,sound:true}:{})};
  const label=key==='counter'?'$(counter:counter)':key==='timer'?'$(timer:timer)':key==='profile_lock'?'Lock $(profile_lock)':k.name;
  return {label,icon:k.icon,actions:[action]};
}
function addAction(key,id=selected) {
  if(key.startsWith('widget:'))return addWidget(key.slice(7),id);
  const item=actionTemplate(key);if(!item)return;
  inspectorTab='actions';
  mutate(()=>{selected=id;let b=current();if(!b){b={id,label:item.label,icon:item.icon,color:item.color||'#35D07F',actions:[]};buttons().push(b);}if(editList==='actions')b.actions??=[];else b[editList]??=[];activeActions().push(...clone(item.actions));});
  toast(activeActions().length>1?'Action added. Steps run from top to bottom.':'Action added. Adjust its settings under the keys.');
}

/* The steps of a key as one readable line: "1 Open program: chrome.exe → 2 Hotkey: ctrl+t". */
function stepDetail(action) {
  const value = ['target', 'path', 'keys', 'text', 'url', 'command', 'name', 'page', 'profile', 'variable', 'op'].map(key => action[key]).find(item => typeof item === 'string' && item);
  return value ? `${(kinds[action.type] || kinds.hotkey).name}: ${value.length > 28 ? value.slice(0, 27) + '…' : value}` : (kinds[action.type] || kinds.hotkey).name;
}
function stepSummary(actions) {
  const shown = actions.slice(0, 3).map((action, index) => `${actions.length > 1 ? index + 1 + ' ' : ''}${stepDetail(action)}`);
  return shown.join(' → ') + (actions.length > 3 ? `  (+${actions.length - 3} more)` : '');
}
/* What a rule like "process:claude.exe" means, in plain words. */
function describeRule(rule) {
  const text = String(rule).trim();
  if (text.startsWith('title:')) return `when the window title has “${text.slice(6).trim()}”`;
  if (text.startsWith('process:')) return `when ${text.slice(8).trim()} runs in the window in front`;
  return `when ${text} is in front`;
}

/* One icon family for the action library (the old text glyphs differed in weight and size). */
const ACTION_SVG = {
  bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  edit: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  home: '<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
  list: '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>',
  loop: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  minus: '<path d="M5 12h14"/>',
  pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
  wifi: '<path d="M5 13a10 10 0 0 1 14 0"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 20 0"/><line x1="12" x2="12.01" y1="20" y2="20"/>'
};
function actionSymbol(name) {
  const node = element('span', {class: 'action-symbol', 'aria-hidden': 'true'});
  if (ACTION_SVG[name]) node.innerHTML = `<svg viewBox="0 0 24 24">${ACTION_SVG[name]}</svg>`; else node.textContent = icons[name] || '';
  return node;
}

/* Ready-made widgets: a wide key that shows something live. The host fills in the text; the list matches host/widgets.py. */
const WIDGETS = [
  {kind: 'clock', name: 'Clock', sub: 'The time, the date and how far the day is', icon: 'lc:e087', span: 2, color: '#4DD0E1', path: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'},
  {kind: 'date', name: 'Date', sub: 'The day, the week and the day of the year', icon: 'lc:e063', span: 2, color: '#B388FF', path: '<path d="M8 2v3"/><path d="M16 2v3"/><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/>'},
  {kind: 'cpu', name: 'Processor', sub: 'Load, temperature and clock speed', icon: 'lc:e0a9', span: 2, color: '#58E09B', path: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="8" y="8" width="8" height="8" rx="1"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>'},
  {kind: 'gpu', name: 'Graphics card', sub: 'Load, temperature and frames per second', icon: 'lc:e11d', span: 2, color: '#FFB74D', path: '<rect width="20" height="14" x="2" y="3" rx="2"/><path d="M8 21h8M12 17v4"/>'},
  {kind: 'ram', name: 'Memory', sub: 'How much memory is in use', icon: 'lc:e445', span: 2, color: '#64B5F6', path: '<rect x="2" y="6" width="20" height="10" rx="2"/><path d="M6 18v-2M10 18v-2M14 18v-2M18 18v-2"/>'},
  {kind: 'network', name: 'Network', sub: 'Download and upload speed', icon: 'lc:e046', span: 2, color: '#4DD0E1', path: '<path d="m3 16 4 4 4-4"/><path d="M7 20V4"/><path d="m21 8-4-4-4 4"/><path d="M17 4v16"/>'},
  {kind: 'volume', name: 'Volume', sub: 'Speaker level and the microphone', icon: 'lc:e1ab', span: 2, color: '#B388FF', path: '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.4 18.4a9 9 0 0 0 0-12.8"/>'},
  {kind: 'agents', name: 'AI agents', sub: 'Who works and who waits for you', icon: 'lc:e1bb', span: 3, color: '#58E09B', path: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>'},
  {kind: 'calendar', name: 'Next meeting', sub: 'Your next meeting from your calendar (set it in Program settings)', icon: 'lc:e304', span: 3, color: '#64B5F6', path: '<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4M8 2v4M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>'}
];
/* Put a widget on a slot: an empty slot gets a new wide key, a key that is already there starts showing the widget. */
function addWidget(kind,id=selected) {
  const widget=WIDGETS.find(w=>w.kind===kind);if(!widget)return;
  const there=visibleButtons().find(b=>b.id===id);
  const span=[widget.span,2].find(size=>spanFits(id,Math.max(size,there?.span||1),there?[there]:[]));
  if(!span)return toast(`${widget.name} needs ${widget.span} free slots side by side on one row. Free the slot to the right first.`);
  mutate(()=>{selected=id;
    if(there){there.span=Math.max(span,there.span||1);there.live=kind;}
    else buttons().push({id,label:widget.name,icon:widget.icon,color:widget.color,span,live:kind,actions:[]});});
  toast(`${widget.name} widget added. The panel fills in the text.`);
}
