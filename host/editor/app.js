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
  delay:{name:'Wait',icon:'pause',field:'ms',label:'Delay (milliseconds)',placeholder:'500',group:'More actions'},
  shell:{name:'Run command',icon:'settings',field:'command',label:'Command',placeholder:'The command runs when the button is pressed',group:'Advanced'},
  http:{name:'HTTP request',icon:'wifi',field:'url',label:'Address',placeholder:'https://…',group:'Advanced'},
  press:{name:'Trigger another button',icon:'loop',field:'id',label:'Button number (1–18)',group:'Advanced'},
  audio:{name:'Mute / unmute audio',icon:'settings',field:'target',label:'Device',group:'On the computer'},
  counter:{name:'Counter',icon:'plus',field:'name',label:'Counter name',placeholder:'for example laps',group:'On the computer'},
  timer:{name:'Timer',icon:'pause',field:'name',label:'Timer name',placeholder:'for example tea',group:'On the computer'},
  set:{name:'Set variable',icon:'edit',field:'variable',label:'Variable name',group:'Advanced'},
  state:{name:'Set button state',icon:'loop',field:'button',label:'Button number (1–18)',group:'Advanced'},
  home:{name:'Go home',icon:'home',field:null,label:'Go to the first page of the default profile',group:'Navigation'},
};
// Sensors the host provides, with the ranges and thresholds of the bundled status page.
const gaugeSensors={
  cpu_load:['CPU load',{max:100,unit:'%',warn:85,critical:97}],cpu_temp:['CPU temperature',{max:100,unit:'C',warn:80,critical:90}],
  cpu_power:['CPU power',{max:170,unit:'W',warn:130,critical:160}],cpu_clock:['CPU clock',{max:5500,fmt:'ghz'}],
  ram:['RAM',{max:100,unit:'%',warn:85,critical:95}],disk:['Disk',{max:100,unit:'%',warn:90,critical:97}],
  gpu_load:['GPU load',{max:100,unit:'%'}],vram_used_gb:['VRAM',{percent_key:'vram',max:100,fmt:'gb',warn:85,critical:95}],
  gpu_temp:['GPU temperature',{max:110,unit:'C',warn:85,critical:100}],gpu_power:['GPU power',{max:350,unit:'W',warn:320,critical:360}],
  gpu_clock:['GPU clock',{max:2600,fmt:'ghz'}],gpu_fan:['GPU fan',{max:3000}],
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
      mutate(()=>{if(current())appearance().icon=item.id;});
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

function element(tag, attrs={}, ...children) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)) {
    if(key==='text') node.textContent=value;
    else if(key==='class') node.className=value;
    else if(key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if(value!==undefined && value!==null) node.setAttribute(key,String(value));
  }
  for(const child of children.flat()) if(child) node.append(child);
  return node;
}
const button=(text,fn,cls='quiet',title) => element('button',{text,class:cls,onclick:fn,type:'button',title});
const text=(tag,value,cls) => element(tag,{text:value,class:cls||''});
function toast(message) {$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4800);}
async function api(path, data) {
  const response=await fetch('/api/'+path, {method:data===undefined?'GET':'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json','X-Deck-Request':'1'},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();
  if(!response.ok) {const error=new Error(result.error||'The operation failed');error.status=response.status;throw error;}
  return result;
}
function buttons() {return config.profiles[profile].pages[page];}
function profileButtons(item) {return [...Object.values(item.pages).flat(),...(item.pinned||[])];}
function rewriteActions(items,transform) {for(const b of items)for(const holder of [b,...(b.states||[])])holder.actions=(holder.actions||[]).flatMap(action=>{const changed=transform(action);return changed?[changed]:[];});}
function visibleButtons() {const values=new Map(buttons().map(b=>[b.id,b]));for(const b of config.profiles[profile].pinned||[])values.set(b.id,b);return [...values.values()];}
function current() {return visibleButtons().find(b=>b.id===selected);}
function owner(id=selected) {const pins=config.profiles[profile].pinned||[];return pins.some(b=>b.id===id)?pins:buttons();}
function appearance(b=current()) {return b?.states?.[editState]||b;}
function activeActions() {const b=current();return b.states?b.states[Math.min(editState,b.states.length-1)].actions:b.actions;}
function togglePin() {mutate(()=>{const b=current(),list=owner(),p=config.profiles[profile];list.splice(list.indexOf(b),1);p.pinned??=[];if(list===p.pinned){const at=buttons().findIndex(v=>v.id===b.id);if(at>=0)buttons().splice(at,1);buttons().push(b);}else p.pinned.push(b);});}
function uniqueName(base,names) {let name=`${base} copy`,number=2;while(names.includes(name))name=`${base} copy ${number++}`;return name;}
function clearButton() {if(!current())return;mutate(()=>{const list=owner(),at=list.findIndex(x=>x.id===selected);if(at>=0)list.splice(at,1);});}
function duplicateButton() {
  const source=current(),slot=Array.from({length:18},(_,i)=>i+1).find(id=>!visibleButtons().some(b=>b.id===id));
  if(!source)return;if(!slot)return toast('This page has no free slots.');
  mutate(()=>{buttons().push({...clone(source),id:slot});selected=slot;editState=0;});
  toast(`The button was duplicated to slot ${slot}.`);
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
    if(!b.label?.trim()) return 'Give the button a name';
    if((b.states||[]).some(state=>state.label!==undefined&&!String(state.label).trim()))return 'Give every state of the toggle button a name';
    for(const holder of [b,...(b.states||[])]) for(const a of holder.actions||[]) {
      const kind=kinds[a.type];
      if(!kind) return 'Unknown action';
      if(kind.field && a.type!=='text' && (a[kind.field]===undefined || String(a[kind.field]).trim()==='')) return 'Fill in '+kind.label.toLowerCase();
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
  const error=draftError();setSaveState(error?'Draft · '+error:'Saving …',error?'Fill in the field, or undo the change.':'The change is sent automatically to the active page.');
  if(!error&&!conflicted)saveTimer=setTimeout(()=>save().catch(showError),650);
}
function mutate(fn,refresh=true,key=null) {remember(key);fn();changed();if(refresh)renderInspector();}
function showError(error) {setSaveState('Not saved',error.message);toast(error.message);if(error.status===409){conflicted=true;$('#reload').hidden=false;}}
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
      setSaveState('✓ Saved on the PC',dashboard.device?.connected?(same?'This page is up to date on the panel.':`The panel shows ${dashboard.device.profile} / ${dashboard.device.page}. Press “Show on device” to switch.`):'Connect the panel and start the host to synchronize.');}
  } finally {saving=false;saveInFlight=null;}
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
function moveSlot(source,target) {
  if(source===target)return;
  mutate(()=>{const from=visibleButtons().find(b=>b.id===source),to=visibleButtons().find(b=>b.id===target);if(!from)return;from.id=target;if(to)to.id=source;selected=target;});
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
    if(kind==='agent')return dashboard.agents?.[name]?'ON':'OFF';
    if(kind==='profile'&&!name)return profile;if(kind==='page'&&!name)return page;
    if(kind==='time'&&!name)return `${two(now.getHours())}:${two(now.getMinutes())}`;
    if(kind==='date'&&!name)return `${two(now.getDate())}.${two(now.getMonth()+1)}`;
    if(kind==='var'&&name)return String(dashboard.vars?.[name]??'');
    if(kind==='stat'&&name)return String(dashboard.stats?.[name]??'--');
    return match;});
  return text.replace(/[\u0000-\u001f]/g,' ');
}
function gaugeVisual(b,live) {
  const NS='http://www.w3.org/2000/svg',D=108,width=11,r=(D-width)/2,C=2*Math.PI*r,arc=C*.75;
  const p=Math.max(0,Math.min(100,live?live.p:0)),color=live?.color||b.color||'#35D07F';
  const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox',`0 0 ${D} ${D}`);svg.setAttribute('class','gauge-ring');
  const rings=[[arc,'#25343C']];if(p>0)rings.push([arc*p/100,color]);
  for(const [dash,stroke] of rings) {
    const circle=document.createElementNS(NS,'circle');
    const attributes={cx:D/2,cy:D/2,r,fill:'none',stroke,'stroke-width':width,'stroke-linecap':'round','stroke-dasharray':`${dash} ${C}`,transform:`rotate(135 ${D/2} ${D/2})`};
    for(const [name,value] of Object.entries(attributes))circle.setAttribute(name,value);
    svg.append(circle);
  }
  return svg;
}
function deviceShowsSelection() {const d=dashboard.device;return !!d?.connected&&d.profile===profile&&d.page===page;}
function renderGrid() {
  const grid=$('#deck-grid');const focused=document.activeElement?.dataset.slot;
  const live=deviceShowsSelection()?(dashboard.device?.gauges||{}):{};
  grid.replaceChildren(...Array.from({length:18},(_,index)=>{
    const id=index+1,base=visibleButtons().find(b=>b.id===id),b=base&&{...base,...(id===selected?appearance(base):base.states?.[0]||{})};
    const tile=element('button',{class:'deck-key'+(!b?' empty':'')+(id===selected?' selected':''),type:'button',draggable:'false',
      'data-slot':id,'aria-label':`Button ${id}: ${b?.label||'Empty slot'}`,'aria-pressed':id===selected,
      onclick:()=>{selected=id;editState=0;renderGrid();renderInspector();}});
    tile.style.left=`${DEVICE.x+(index%6)*(DEVICE.cell+DEVICE.gap)}px`;
    tile.style.top=`${DEVICE.y+Math.floor(index/6)*(DEVICE.cell+DEVICE.gap)}px`;
    tile.style.setProperty('--key-color',b?.color||'#92edba');
    if(b?.bg)tile.style.background=b.bg;
    if(b?.border){tile.style.borderColor=b.border;tile.style.borderWidth='3px';}
    if(b?.text_color)tile.style.setProperty('--key-text',b.text_color);
    tile.append(text('span',String(id),'slot-number'));
    if(!b)tile.append(text('span','+','empty-plus'));
    else {
      const geometry=tileGeometry(b);
      if(b.gauge) {
        const value=text('span',live[id]?.t||'--','gauge-value');value.style.color=live[id]?.color||b.color||'#35D07F';
        tile.append(gaugeVisual(b,live[id]),value);
      } else {
        const symbol=iconVisual(b.icon,b.color,'key-symbol');
        if(b.icon?.startsWith('im:'))symbol.classList.add('symbol-image');
        if(geometry.symbolTop)symbol.classList.add('symbol-top');
        tile.append(symbol);
      }
      const label=text('span',resolveLabel(b.label),'key-label');
      label.style.top=geometry.labelTop+'px';label.style.fontSize=geometry.px+'px';
      if(b.title?.bold)label.style.fontWeight='700';label.hidden=geometry.hidden;tile.append(label);
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
    tile.addEventListener('keydown',event=>{const delta={ArrowRight:1,ArrowLeft:-1,ArrowDown:6,ArrowUp:-6}[event.key];if(delta){event.preventDefault();selected=Math.max(1,Math.min(18,id+delta));renderGrid();renderInspector();$(`[data-slot="${selected}"]`).focus();}});
    return tile;
  }));
  if(focused)$(`[data-slot="${focused}"]`)?.focus();
}
function fitDevice() {
  const frame=$('#device-frame'),screen=$('#device-screen');if(!frame||!screen)return;
  const scale=frame.clientWidth/1024;screen.style.transform=`scale(${scale})`;frame.style.height=`${600*scale}px`;
}
function tickClock() {const clock=$('#screen-clock');if(clock)clock.textContent=new Date().toTimeString().slice(0,5);}
function setupMoreMenu() {
  const toggle=$('#more-toggle'),menu=$('#more-menu');
  const close=()=>{menu.hidden=true;toggle.setAttribute('aria-expanded','false');};
  toggle.onclick=event=>{event.stopPropagation();menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));};
  menu.addEventListener('click',event=>{if(event.target.closest('button'))close();});
  document.addEventListener('click',event=>{if(!event.target.closest('.more'))close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')close();});
}
async function syncPanel() {
  if(!$('#sync').checked||!dashboard.running)return;
  try{await api('command/activate',{profile,page});}catch(error){/* unsaved or unknown page: the panel keeps its page */}
}
let lastDevicePath='';
function followDevice() {
  const d=dashboard.device;if(!$('#sync').checked||!d?.connected||!d.profile)return;
  const path=d.profile+'|'+d.page;if(path===lastDevicePath)return;lastDevicePath=path;
  if(config.profiles[d.profile]?.pages?.[d.page]&&(d.profile!==profile||d.page!==page)){profile=d.profile;page=d.page;selected=1;editState=0;renderAll();}
}
function actionTemplate(key) {
  if(key.startsWith('pack:')) {const pack=actionCatalog.packs[Number(key.split(':')[1])];if(!pack)return;return {label:pack.name,icon:pack.icon||'ok',color:pack.color||'#35D07F',actions:clone(pack.actions)};}
  if(key.startsWith('preset:')) {const preset=presets[Number(key.split(':')[1])];if(!preset)return;return {label:preset.name,icon:preset.icon,actions:[{type:'hotkey',keys:preset.keys}]};}
  const k=kinds[key];if(!k)return;
  const value={hotkey:'',text:'',open:'',folder:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,back:null,page:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,
    profile:Object.keys(config.profiles).find(p=>p!==profile)||profile,delay:500,shell:'',http:'',press:1,set:'',state:1,audio:'mic',counter:'counter',timer:'timer'}[key];
  const action={type:key,...(k.field?{[k.field]:value}:{}),...(key==='http'?{method:'GET'}:{}),...(key==='state'?{state:'next'}:{}),...(key==='audio'?{op:'toggle'}:{}),
    ...(key==='counter'?{op:'inc',step:1}:{}),...(key==='timer'?{op:'toggle',seconds:300,sound:true}:{})};
  const label=key==='counter'?'$(counter:counter)':key==='timer'?'$(timer:timer)':k.name;
  return {label,icon:k.icon,actions:[action]};
}
function addAction(key,id=selected) {
  const item=actionTemplate(key);if(!item)return;
  mutate(()=>{selected=id;let b=current();if(!b){b={id,label:item.label,icon:item.icon,color:item.color||'#35D07F',actions:[]};buttons().push(b);}b.actions??=[];activeActions().push(...clone(item.actions));});
  toast(activeActions().length>1?'Action added. Steps run from top to bottom.':'Action added. Adjust the settings on the right.');
}
function renderLibrary() {
  const search=$('#action-search').value.toLocaleLowerCase();const list=$('#actions-library');list.replaceChildren();
  const make=(name,icon,sub,key)=>{if(!(name+' '+sub).toLocaleLowerCase().includes(search))return null;
    const item=button('',()=>addAction(key),'action-preset');item.draggable=false;item.dataset.action=key;item.setAttribute('aria-label','Add '+name);
    item.append(text('span',icons[icon],'action-symbol'),element('span',{},text('span',name),text('small',sub)));
    item.addEventListener('dragstart',e=>{e.dataTransfer.setData('application/x-deck-action',key);e.dataTransfer.effectAllowed='copy';});return item;};
  if(('installed programs app launcher'.includes(search)||!search))list.append(button('▦ Installed programs',openProgramPicker,'program-launcher'));
  const groups=new Map();for(const [key,k] of Object.entries(kinds)){const sub=key==='page'?'Folders and subpages':key==='hotkey'?'Record a key combination':key==='open'?'Choose directly from the computer':key==='delay'?'Between steps in a multi-action':'Customize as needed';const item=make(k.name,k.icon,sub,key);if(item){if(!groups.has(k.group))groups.set(k.group,[]);groups.get(k.group).push(item);}}
  for(const [group,items] of groups){list.append(text('div',group.toUpperCase(),'library-group'),...items);}
  if(actionCatalog.packs.length){const packed=new Map();actionCatalog.packs.forEach((p,i)=>{const item=make(p.name,p.icon||'ok',p.actions.length>1?`${p.actions.length} actions`:'Ready-made action','pack:'+i);if(item){if(!packed.has(p.group))packed.set(p.group,[]);packed.get(p.group).push(item);}});for(const [group,items] of packed)list.append(text('div',group.toUpperCase(),'library-group'),...items);}
  else {const ready=presets.map((p,i)=>make(p.name,p.icon,'Ready-made action','preset:'+i)).filter(Boolean);if(ready.length)list.append(text('div','READY TO USE','library-group'),...ready);}
  if(!list.children.length)list.append(element('div',{class:'library-empty'},text('strong','No matches'),text('span','Try another search term.')));
}
function applyProgramDetails(result,index=0) {
  if(!result?.target)return;
  mutate(()=>{
    const base=current(),actions=activeActions();
    if(!base||!actions?.[index])return;
    Object.assign(actions[index],{type:'open',target:result.target,process:result.process||'',reuse:result.reuse!==false});
    const view=appearance(base);view.label=result.name||view.label;view.icon=result.icon||view.icon;
  });
  toast(`“${result.name}” now uses the program icon and focuses an open window.`);
}
async function installProgram(target,id=selected) {
  if(!target)return;
  const result=await api('command/program',{target});
  placeProgram(result,id);
}
function placeProgram(result,id=selected) {
  mutate(()=>{
    selected=id;editState=0;
    const list=owner(id),old=list.findIndex(item=>item.id===id);
    if(old>=0)list.splice(old,1);
    list.push({id,label:result.name,icon:result.icon||'folder',color:'#35D07F',
      actions:[{type:'open',target:result.target,process:result.process||'',reuse:result.reuse!==false}]});
  });
  $('#program-dialog').close();
  toast(`“${result.name}” was placed on button ${id}.`);
}
function renderProgramResults() {
  const query=$('#program-search').value.trim().toLocaleLowerCase();
  const matches=installedPrograms.map((item,index)=>({...item,index})).filter(item=>!query||item.name.toLocaleLowerCase().includes(query));
  const list=$('#program-results');
  list.replaceChildren(...matches.map(item=>{
    const choice=button('',()=>installProgram(item.target).catch(showError),'program-choice',`Put ${item.name} on the selected button`);
    choice.dataset.program=item.index;choice.dataset.label=item.name;choice.append(text('span',item.name.slice(0,1).toUpperCase(),'program-symbol'),
      element('span',{},text('strong',item.name),text('small','Drag to a button or click for the selected slot')));
    return choice;
  }));
  if(!matches.length)list.append(element('div',{class:'program-empty'},text('strong','No programs found'),text('span','Try a shorter search term, or use “Choose program file”.')));
  $('#program-count').textContent=`${matches.length} of ${installedPrograms.length} programs`;
}
async function openProgramPicker() {
  const dialog=$('#program-dialog');dialogReturnFocus=document.activeElement;
  dialog.show();$('#program-results').replaceChildren(text('p','Reading the Start menu …','hint program-loading'));
  try {
    if(!installedPrograms.length)installedPrograms=(await api('programs')).programs||[];
    $('#program-search').value='';renderProgramResults();$('#program-search').focus();
  } catch(error) {dialog.close();showError(error);}
}
function field(label,value,handler,{type='text',placeholder='',values=null,multiline=false}={}) {
  const input=values?element('select'):element(multiline?'textarea':'input',{type,placeholder});
  if(values)options(input,values,value);else input.value=value??'';
  input.addEventListener(values?'change':'input',()=>handler(type==='number'?Number(input.value):input.value));
  return element('label',{},text('span',label),input);
}
function editAction(index,key,value) {mutate(()=>activeActions()[index][key]=value,false,editKey('action',index,key));}
function renderInspector() {
  recording=null;const panel=$('#inspector'),base=current(),b=appearance();panel.replaceChildren();
  panel.append(element('div',{class:'inspector-title'},element('div',{},text('div',`BUTTON ${String(selected).padStart(2,'0')}`,'section-label'),text('h2',b?'Customize the button':'An empty slot'))));
  if(!b){panel.append(element('div',{class:'empty-inspector'},text('strong','What do you want here?'),text('p','Drag an action here from the list on the left. Or pick one of the shortcuts below.')));
    panel.append(button('▦ Choose installed program',openProgramPicker,'add-action'),button('＋ Add hotkey',()=>addAction('hotkey'),'add-action'),button('▱ Open file or program',()=>addAction('open'),'add-action'),button('▶ Play / pause',()=>addAction('preset:3'),'add-action'));if(clipboard)panel.append(button('Paste copied button',pasteButton,'add-action'));return;}
  const meter=text('small','','label-meter');
  const updateMeter=()=>{const full=expandLabel(appearance()?.label),bytes=new TextEncoder().encode(full).length,variable=/[$][(]/.test(appearance()?.label||'');
    meter.classList.toggle('over',bytes>LABEL_BYTES);
    meter.textContent=bytes>LABEL_BYTES?`Too long for the panel: it shows “${panelLabel(full)}”`:`${bytes} / ${LABEL_BYTES} bytes on the panel${variable?' with the current values':''}`;};
  const nameField=field('Button name',b.label,value=>{mutate(()=>appearance().label=value,false,editKey('label'));updateMeter();},{placeholder:'A short, clear name'});
  nameField.append(meter);updateMeter();panel.append(nameField);
  const appearanceRow=element('div',{class:'appearance-row'},text('span','Icon color','hint'));
  const color=element('input',{type:'color',value:b.color||'#35D07F','aria-label':'Icon color'});color.addEventListener('input',()=>{mutate(()=>appearance().color=color.value,false,editKey('color'));panel.querySelector('.selected-icon-image')?.replaceWith(iconVisual(current().icon,color.value,'selected-icon-image'));});appearanceRow.append(color,text('span','Shown on the panel','hint'));panel.append(appearanceRow);
  const selectedIcon=packIcons.get(b.icon);
  panel.append(element('div',{class:'selected-pack-icon'},iconVisual(b.icon,b.color,'selected-icon-image'),element('div',{},text('strong',selectedIcon?.name||iconNames[b.icon]||'Default icon'),button(iconPack?`Choose from ${iconPack.count.toLocaleString('en-US')} icons …`:'Open the large icon library …',openIcons,'text-button'))));
  const upload=element('input',{type:'file',accept:'image/png,image/jpeg,image/gif,image/webp',hidden:'hidden'});upload.onchange=()=>chooseImage(upload.files[0]).catch(showError);panel.append(upload,button('Image from file …',()=>upload.click(),'outline'));
  panel.append(element('div',{class:'title-controls'},field('Text size',String(base.title?.size||16),v=>mutate(()=>{base.title??={};base.title.size=Number(v);}),{values:['16','20','24','28']}),field('Position',base.title?.position||'bottom',v=>mutate(()=>{base.title??={};base.title.position=v;}),{values:[['bottom','Bottom'],['top','Top'],['middle','Middle'],['hidden','Hide text']]})));
  panel.append(element('div',{class:'option-buttons'},button(base.title?.bold?'Bold text ✓':'Bold text',()=>mutate(()=>{base.title??={};base.title.bold=!base.title.bold;}),'outline'),button(config.profiles[profile].pinned?.includes(base)?'◆ Unpin':'◇ Pin to all pages',togglePin,'outline')));
  panel.append(field('Button type',base.states?'Toggle button':'Normal button',value=>mutate(()=>{if(value==='Toggle button'){base.states=[{label:base.label,icon:base.icon,color:base.color,actions:clone(base.actions||[])},{label:base.label+' · on',icon:base.icon,color:'#FFA868',actions:clone(base.actions||[])}];}else if(base.states){const first=base.states[0];for(const key of ['label','icon','color'])if(first[key]!==undefined)base[key]=first[key];base.actions=clone(first.actions||[]);delete base.states;}editState=0;}),{values:['Normal button','Toggle button']}));
  if(base.states){panel.append(field('Edit state',String(editState+1),value=>{editState=Number(value)-1;renderGrid();renderInspector();},{values:base.states.map((_,i)=>String(i+1))}),text('p','A press runs this state and then shows the next one. This is local button state, not confirmed app status.','hint'));}
  renderGauge(panel,base);
  renderBind(panel,base);
  renderHold(panel,base);
  renderStyle(panel);
  const choices=element('div',{class:'icon-grid',role:'group','aria-label':'Choose icon'});
  for(const [key,glyph] of Object.entries(icons)) {const item=button(glyph,()=>mutate(()=>appearance().icon=key),'icon-choice'+((b.icon||'ok')===key?' active':''),iconNames[key]);item.setAttribute('aria-label',iconNames[key]);item.setAttribute('aria-pressed',(b.icon||'ok')===key);choices.append(item);}
  panel.append(element('details',{class:'quick-icons'},text('summary','Quick icons'),choices));
  panel.append(text('div',(activeActions()?.length>1?'MULTI-ACTION · ':'ACTIONS · ')+(activeActions()?.length||0)+' STEPS','section-label'));
  (activeActions()||[]).forEach((action,index)=>panel.append(renderStep(action,index,activeActions().length)));
  const addSelect=element('select',{'aria-label':'Add a new action step'});addSelect.append(element('option',{value:'',text:'＋ Add action …'}));for(const [key,k] of Object.entries(kinds))addSelect.append(element('option',{value:key,text:k.name}));addSelect.addEventListener('change',()=>{if(addSelect.value)addAction(addSelect.value);});panel.append(addSelect);
  panel.append(element('div',{class:'inspector-tools'},button('Test',()=>testButton().catch(showError),'outline'),button('Copy',copyButton,'outline'),button('Paste',pasteButton,'outline'),button('Clear button',clearButton,'quiet danger')));
  panel.append(field('Move to slot',String(selected),value=>moveSlot(selected,Number(value)),{values:Array.from({length:18},(_,i)=>String(i+1))}));
  panel.append(text('p','Changes are saved automatically. The button action runs only when you press the panel.','hint'));
  panel.append(text('p','Shortcuts: Ctrl+Z / Ctrl+Y undo and redo · Ctrl+C / Ctrl+V copy and paste · Ctrl+D duplicate · Delete clears the key · Ctrl+S saves now','hint shortcuts'));
}
function renderHold(panel,base) {
  const keys=base.hold_actions?.[0]?.type==='hotkey'?base.hold_actions[0].keys:'';
  panel.append(field('Long-press hotkey (optional)',keys,value=>mutate(()=>{const keys=value.trim();if(keys)base.hold_actions=[{type:'hotkey',keys}];else delete base.hold_actions;}),{placeholder:'for example ctrl+shift+m'}));
  panel.append(text('p','Hold the key for about half a second to send this instead of the normal actions.','hint'));
}
function renderBind(panel,base) {
  if(!base.states)return;
  const choices=[['','Off · a press cycles the states'],['mic_muted','Microphone muted'],['speaker_muted','Speakers muted'],['media_playing','Media playing'],['__timer','A timer is running …']];
  if(base.bind?.startsWith('timer-running:'))choices.splice(-1,0,[base.bind,`Timer “${base.bind.slice(14)}” is running`]);
  panel.append(field('Follow PC state',base.bind||'',value=>mutate(()=>{
    if(value==='__timer'){const name=(prompt('Name of the timer to follow')||'').trim();if(/^[A-Za-z0-9_.-]{1,64}$/.test(name))base.bind=`timer-running:${name}`;else if(name)toast('Use letters, digits, dots, dashes or underscores.');}
    else if(value)base.bind=value;else delete base.bind;}),{values:choices}));
  if(base.bind)panel.append(text('p','State 1 shows while the condition is off, state 2 while it is on.','hint'));
}
function renderGauge(panel,base) {
  const gauge=base.gauge,choices=[['','Off · show the icon'],...Object.entries(gaugeSensors).map(([key,[name]])=>[key,name])];
  if(gauge&&!gaugeSensors[gauge.key])choices.push([gauge.key,gauge.key]);
  panel.append(field('Live gauge',gauge?.key||'',key=>mutate(()=>{if(key)base.gauge={key,...clone(gaugeSensors[key]?.[1]||{max:100})};else delete base.gauge;}),{values:choices}));
  if(!gauge)return;
  const number=(label,name,optional)=>{
    const input=element('input',{type:'number',step:'any',value:gauge[name]??'',placeholder:optional?'Off':'','aria-label':label});
    input.addEventListener('change',()=>{
      const raw=input.value.trim(),value=Number(raw);
      if(raw===''&&optional)return mutate(()=>delete base.gauge[name],false);
      if(raw===''||!Number.isFinite(value)||name==='max'&&value<=0){input.value=gauge[name]??'';return toast(name==='max'?'The full ring needs a value above 0.':'Enter a number, or leave it empty to turn it off.');}
      mutate(()=>base.gauge[name]=value,false);
    });
    return element('label',{},text('span',label),input);
  };
  panel.append(element('div',{class:'gauge-controls'},number('Full ring at','max'),number('Amber from','warn',true),number('Red from','critical',true)));
  if((gauge.fmt||'int')==='int'){
    const unit=field('Unit after the value',gauge.unit||'',value=>mutate(()=>{if(value)base.gauge.unit=value;else delete base.gauge.unit;},false,editKey('gauge-unit')),{placeholder:'%, C or W'});
    unit.querySelector('input').maxLength=3;panel.append(unit);
  }
  panel.append(text('p','The host fills in the value and the ring. The key turns amber and red at the thresholds; without a sensor it shows --.','hint'));
}
function renderStep(action,index,count) {
  const k=kinds[action.type]||kinds.hotkey;
  const step=element('section',{class:'step','aria-label':`Step ${index+1}: ${k.name}`,draggable:'false','data-step':index});
  step.addEventListener('dragstart',event=>{if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return event.preventDefault();event.dataTransfer.setData('application/x-deck-step',String(index));event.stopPropagation();});
  step.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer.types).includes('application/x-deck-step'))event.preventDefault();});
  step.addEventListener('drop',event=>{const value=event.dataTransfer.getData('application/x-deck-step');if(value==='')return;event.preventDefault();const source=Number(value);mutate(()=>{const actions=activeActions();actions.splice(index,0,actions.splice(source,1)[0]);});});
  const move=delta=>{if(index+delta<0||index+delta>=count)return;mutate(()=>{const a=activeActions();[a[index],a[index+delta]]=[a[index+delta],a[index]];});};
  const up=button('↑',()=>move(-1),'quiet','Move step up'),down=button('↓',()=>move(1),'quiet','Move step down');up.disabled=index===0;down.disabled=index===count-1;
  step.append(element('div',{class:'step-header'},text('strong',`${index+1}. ${k.name}`),up,down,button('×',()=>mutate(()=>activeActions().splice(index,1)),'quiet danger','Remove step')));
  let values=action.type==='audio'?['mic','speaker']:['page','folder'].includes(action.type)?Object.keys(config.profiles[profile].pages):action.type==='profile'?Object.keys(config.profiles):null;
  if(action.type==='back'){step.append(text('p','Goes back one level in the folder stack.','hint'));return step;}
  if(action.type==='home'){step.append(text('p','Opens the first page of the default profile and keeps it selected until you switch the active program.','hint'));return step;}
  const parameter=field(k.label,action[k.field],value=>editAction(index,k.field,value),{type:['delay','press','state'].includes(action.type)?'number':'text',placeholder:k.placeholder,values,multiline:['text','shell'].includes(action.type)});
  if(action.type==='open') {
    const input=parameter.querySelector('input');input.setAttribute('data-path',index);parameter.append(button('Choose program …',async()=>{try{const result=await api('command/pick',{kind:'program'});if(result.target){applyProgramDetails(result,index);}}catch(error){showError(error);}},'text-button'));
  }
  step.append(parameter);
  if(action.type==='audio')step.append(field('Operation',action.op||'toggle',value=>editAction(index,'op',value),{values:['toggle','mute','unmute']}));
  if(action.type==='open') {
    const focus=element('label',{class:'check-option'},element('input',{type:'checkbox'}),element('span',{},text('strong','Focus open window'),text('small','Starts the program only when it is not already running.')));
    const checkbox=focus.querySelector('input');checkbox.checked=!!action.reuse;checkbox.onchange=()=>mutate(()=>activeActions()[index].reuse=checkbox.checked);step.append(focus);
    if(action.reuse)step.append(field('Process name',action.process||'',value=>editAction(index,'process',value),{placeholder:'for example chrome.exe'}));
  }
  if(action.type==='hotkey') {const record=button('⌨ Record hotkey',()=>{recording={index,input:parameter.querySelector('input'),button:record};record.textContent='Press the combination · Esc cancels';record.classList.add('recording');record.focus();},'outline record');step.append(record);}
  if(['page','folder'].includes(action.type))step.append(button('＋ Create new subpage',()=>newPage(true,index),'text-button'));
  if(action.type==='http'){step.append(field('Method',action.method||'GET',v=>editAction(index,'method',v),{values:['GET','POST','PUT','PATCH','DELETE']}),field('Body (optional)',action.body||'',v=>editAction(index,'body',v),{multiline:true}));}
  if(action.type==='set')step.append(field('Value',action.value||'',v=>editAction(index,'value',v)));
  if(action.type==='state') {
    const shown=action.state===undefined||action.state==='next'?'next':String(action.state+1);
    step.append(field('State to set',shown,v=>editAction(index,'state',v==='next'?'next':Number(v)-1),{values:['next',...Array.from({length:8},(_,i)=>String(i+1))]}),
      text('p','Sets the toggle state of another button. Choose next to cycle, or a state number to match reality.','hint'));
  }
  if(action.type==='counter')renderCounterStep(step,action,index);
  if(action.type==='timer')renderTimerStep(step,action,index);
  return step;
}
function optionalNumber(label,value,onChange) {
  const input=element('input',{type:'number',step:'1',value:value??'',placeholder:'Off','aria-label':label});
  input.addEventListener('change',()=>onChange(input.value.trim()===''?null:Math.round(Number(input.value))));
  return element('label',{},text('span',label),input);
}
function setOptional(index,key,value) {mutate(()=>{const action=activeActions()[index];if(value===null||Number.isNaN(value))delete action[key];else action[key]=value;},false,editKey('action',index,key));}
function renderCounterStep(step,action,index) {
  const op=action.op||'inc';
  step.append(field('Operation',op,v=>mutate(()=>{activeActions()[index].op=v;}),{values:[['inc','Add'],['dec','Subtract'],['set','Set to a value'],['reset','Reset']]}));
  if(op==='inc'||op==='dec')step.append(field('Step',String(action.step??1),v=>editAction(index,'step',Math.max(1,Math.round(Number(v))||1)),{type:'number'}));
  else step.append(field('Value',String(action.value??0),v=>editAction(index,'value',Math.round(Number(v))||0),{type:'number'}));
  step.append(optionalNumber('Lowest value (optional)',action.min,v=>setOptional(index,'min',v)),optionalNumber('Highest value (optional)',action.max,v=>setOptional(index,'max',v)));
  const wrap=element('label',{class:'check-option'},element('input',{type:'checkbox'}),element('span',{},text('strong','Wrap around'),text('small','Past the highest value it continues at the lowest (needs both limits).')));
  const box=wrap.querySelector('input');box.checked=!!action.wrap;box.onchange=()=>mutate(()=>{activeActions()[index].wrap=box.checked;},false);step.append(wrap);
  step.append(text('p',`Show it in a button name with $(counter:${action.name||'name'}). It is saved, so it survives restarts. For a reset on long press, use the Long-press setting.`,'hint'));
}
function clockToSeconds(value) {
  const parts=String(value).trim().split(':').map(Number);if(!parts.length||parts.length>3||parts.some(n=>!Number.isFinite(n)||n<0))return null;
  return parts.reduce((total,n)=>total*60+n,0)||null;
}
function secondsToClock(seconds) {const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60,two=n=>String(n).padStart(2,'0');return h?`${h}:${two(m)}:${two(s)}`:`${two(m)}:${two(s)}`;}
function renderTimerStep(step,action,index) {
  step.append(field('Operation',action.op||'toggle',v=>mutate(()=>{activeActions()[index].op=v;}),{values:[['toggle','Start, pause and resume'],['start','Start again from the beginning'],['pause','Pause'],['resume','Resume'],['stop','Stop and reset']]}));
  step.append(field('Length (mm:ss or h:mm:ss)',secondsToClock(action.seconds||300),v=>{const seconds=clockToSeconds(v);if(seconds&&seconds<=604800)editAction(index,'seconds',seconds);},{placeholder:'05:00'}));
  step.append(field('Message when finished (optional)',action.notify||'',v=>editAction(index,'notify',v),{placeholder:'for example Tea is ready'}));
  const sound=element('label',{class:'check-option'},element('input',{type:'checkbox'}),element('span',{},text('strong','Play a sound when finished')));
  const box=sound.querySelector('input');box.checked=!!action.sound;box.onchange=()=>mutate(()=>{activeActions()[index].sound=box.checked;},false);step.append(sound);
  const pressed=action.actions?.find(a=>a.type==='press')?.id;
  step.append(optionalNumber('When finished, press key (optional, 1-18)',pressed,v=>mutate(()=>{const target=activeActions()[index];if(v>=1&&v<=18)target.actions=[{type:'press',id:v}];else delete target.actions;},false)));
  step.append(button('◔ Show the countdown ring on this key',()=>mutate(()=>{const base=current();base.gauge={key:`timer:${action.name||'timer'}`,max:action.seconds||300,fmt:'clock'};}),'outline'),
    text('p',`Show the time in a button name with $(timer:${action.name||'name'}) or the ring above. The timer keeps running while Tessera is closed.`,'hint'));
}
function copyButton() {if(!current())return;clipboard=clone(current());toast('The button was copied. Choose a slot and press Ctrl+V.');}
function pasteButton() {if(!clipboard)return toast('Copy a button first.');mutate(()=>{const list=owner(),at=list.findIndex(b=>b.id===selected);if(at>=0)list.splice(at,1);list.push({...clone(clipboard),id:selected});});}
function dialog(title,fields,onSave,saveLabel='Save') {
  const d=$('#form-dialog');dialogReturnFocus=document.activeElement;$('#dialog-title').textContent=title;$('#dialog-error').textContent='';$('#dialog-submit').textContent=saveLabel;
  $('#dialog-fields').replaceChildren(...fields.map(f=>{const label=element('label',{class:'form-field'},text('span',f.label));const input=f.options?element('select',{name:f.name}):element(f.multiline?'textarea':'input',{name:f.name,type:f.type||'text',required:f.required?'required':undefined});if(f.options)options(input,f.options,f.value||f.options[0][0]);else if(f.type==='checkbox')input.checked=!!f.value;else input.value=f.value||'';label.append(input);if(f.note)label.append(text('small',f.note,'hint'));return label;}));
  d.querySelector('form').onsubmit=event=>{if(event.submitter?.value==='cancel')return;event.preventDefault();const form=new FormData(event.target);const values={};for(const f of fields)values[f.name]=f.type==='checkbox'?form.has(f.name):form.get(f.name);try{onSave(values);d.close();}catch(error){$('#dialog-error').textContent=error.message;}};
  d.showModal();setTimeout(()=>d.querySelector('input,textarea')?.focus(),30);
}
function openTemplates() {
  if(!actionCatalog.templates.length)return toast('No templates are available.');
  const choices=actionCatalog.templates.map((template,index)=>[String(index),`${template.name} · ${template.description}`]);
  dialog('Profile templates',[{name:'template',label:'Choose template',options:choices,value:'0',note:'The template is added as a new profile. Your existing profiles are kept.'}],values=>{
    const template=actionCatalog.templates[Number(values.template)];if(!template)throw new Error('Choose a valid template.');
    let name=template.name,suffix=2;while(config.profiles[name])name=`${template.name} ${suffix++}`;
    mutate(()=>{config.profiles[name]=clone(template.profile);profile=name;page=Object.keys(config.profiles[name].pages)[0];selected=1;editState=0;});renderAll();toast(`Profile “${name}” was added.`);
  },'Add profile');
}
function newPage(link=false,index=0) {dialog(link?'Create a subpage':'New page',[{name:'name',label:'Page name',required:true}],values=>{
  const name=values.name.trim();if(!name||config.profiles[profile].pages[name])throw new Error('Choose a new page name.');
  mutate(()=>{config.profiles[profile].pages[name]=[];if(link){activeActions()[index].page=name;activeActions()[index].type='folder';
    config.profiles[profile].pages[name].push({id:17,label:'Back',icon:'home',color:'#A3B2BC',actions:[{type:'back'}]});}else page=name;});renderPages();
});}
function renameProfile(old,name) {
  if(name===old)return;
  if(!name||config.profiles[name])throw new Error('Choose a new profile name.');
  const entries=Object.entries(config.profiles);config.profiles=Object.fromEntries(entries.map(([key,value])=>[key===old?name:key,value]));
  if(config.default_profile===old)config.default_profile=name;
  for(const item of Object.values(config.profiles))rewriteActions(profileButtons(item),a=>a.type==='profile'&&a.profile===old?{...a,profile:name}:a);
  for(const t of config.triggers||[])for(const a of t.actions||[])if(a.type==='profile'&&a.profile===old)a.profile=name;
}
async function profileSettings() {
  let running=[];try{running=(await api('processes')).names||[];}catch(error){}
  const processChoices=[['','— Choose a running program —'],...running.map(name=>[name,name])];
  dialog('Profile settings',[
  {name:'name',label:'Profile name',value:profile,required:true},
  {name:'program',label:'Add a running program',options:processChoices,value:'',note:'Choose the program that activates the profile.'},
  {name:'match',label:'Automatic profile switching rules',value:(config.profiles[profile].match||[]).join(', '),note:'Separate multiple rules with commas. Use process:claude.exe for a terminal process or title:codex for a window title.'},
  {name:'default',label:'Use as default profile',type:'checkbox',value:profile===config.default_profile},
  {name:'remove',label:'Delete the profile and remove actions that point to it',type:'checkbox'}],values=>{
    if(values.remove){
      if(Object.keys(config.profiles).length===1)throw new Error('Keep at least one profile.');
      if(!confirm(`Delete profile “${profile}” and actions that point to it?`))return;
      mutate(()=>{const old=profile;delete config.profiles[old];profile=Object.keys(config.profiles)[0];page=Object.keys(config.profiles[profile].pages)[0];if(config.default_profile===old)config.default_profile=profile;
        for(const item of Object.values(config.profiles))rewriteActions(profileButtons(item),a=>a.type==='profile'&&a.profile===old?null:a);
        for(const t of config.triggers||[])t.actions=(t.actions||[]).filter(a=>!(a.type==='profile'&&a.profile===old));});renderAll();return;
    }
    const name=values.name.trim();if(!name||(name!==profile&&config.profiles[name]))throw new Error('The profile name is already in use.');
    mutate(()=>{renameProfile(profile,name);profile=name;const rules=values.match.split(',').map(s=>s.trim()).filter(Boolean);if(values.program&&!rules.includes(values.program))rules.push(values.program);config.profiles[profile].match=rules;if(values.default)config.default_profile=profile;});renderAll();
  });
}
const brightnessChoices=[100,80,60,40,20],dimAfterChoices=[0,60,300,600,1800,3600],dimLevelChoices=[0,5,10,20];
function displayChoices(values,current,format) {
  const all=values.includes(current)?values:[...values,current].sort((a,b)=>b-a);
  return all.map(v=>[String(v),v===0&&values===dimAfterChoices?'Never':format(v)]);
}
function appSettings() {
  const display={brightness:100,dim_after:300,dim_level:10,...(config.display||{})};
  dialog('Program settings',[
  {name:'autostart',label:'Start the USB host automatically when I sign in',type:'checkbox',value:!!dashboard.autostart,note:'The panel is ready without opening the editor window. You can still open Tessera from the desktop to edit.'},
  {name:'autoProfiles',label:'Switch profile automatically by active program',type:'checkbox',value:config.auto_profiles!==false,note:'Turn off if the panel should stay on the program launcher until you switch profile yourself.'},
  {name:'brightness',label:'Panel brightness',options:displayChoices(brightnessChoices,display.brightness,v=>`${v}%`),value:String(display.brightness)},
  {name:'dimAfter',label:'Dim the panel after',options:displayChoices(dimAfterChoices,display.dim_after,v=>`${Math.round(v/60)} min`),value:String(display.dim_after),note:'The first touch on a dimmed panel only wakes it; it does not press a button.'},
  {name:'dimLevel',label:'Brightness when dimmed',options:displayChoices(dimLevelChoices,display.dim_level,v=>v?`${v}%`:'Off'),value:String(display.dim_level)}
],values=>{mutate(()=>{config.auto_profiles=values.autoProfiles;config.display={brightness:Number(values.brightness),dim_after:Number(values.dimAfter),dim_level:Number(values.dimLevel)};});command('autostart',{enabled:values.autostart}).catch(showError);},'Apply');}
function pageSettings() {dialog('Page settings',[{name:'name',label:'Page name',value:page,required:true},{name:'remove',label:'Delete this page and remove actions that point to it',type:'checkbox'}],values=>{
  const pages=config.profiles[profile].pages,name=values.name.trim(),old=page;
  if(values.remove&&Object.keys(pages).length===1)throw new Error('Keep at least one page.');
  if(!values.remove&&(!name||(name!==old&&pages[name])))throw new Error('Choose a new page name.');
  if(values.remove&&!confirm(`Delete “${old}” and remove actions in this profile that point to the page?`))return;
  mutate(()=>{
    if(values.remove){delete pages[old];page=Object.keys(pages)[0];}
    else {config.profiles[profile].pages=Object.fromEntries(Object.entries(pages).map(([key,value])=>[key===old?name:key,value]));page=name;}
    const update=a=>['page','folder'].includes(a.type)&&a.page===old?(values.remove?null:{...a,page:name}):a;
    rewriteActions(profileButtons(config.profiles[profile]),update);
    if(config.default_profile===profile)for(const t of config.triggers||[])t.actions=(t.actions||[]).flatMap(a=>{const changed=update(a);return changed?[changed]:[];});
  });renderAll();
});}
async function exportConfig() {await save();const bundle=await api('export');const blob=new Blob([JSON.stringify(bundle,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=element('a',{href:url,download:'tessera-profiles.json'});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function importConfig(file) {
  if(!file)return;if(file.size>16*1024*1024)throw new Error('The configuration is too large.');const data=JSON.parse(await file.text());
  if(!data.profiles||!Object.keys(data.profiles).length)throw new Error('The file contains no profiles.');
  const names=Object.keys(data.profiles);if(!confirm(`Replace the configuration with ${names.length} profiles from “${file.name}”? ${(data.triggers||[]).length} automatic rules are included. You can undo.`))return;
  const {assets:bundledAssets,redacted,...bundle}=data;
  const {findings}=await api('command/review',{config:bundle});
  if(findings.length){
    const listed=findings.slice(0,8).map(f=>`• ${f.risk.toUpperCase()}${f.automatic?' (automatic)':''}: ${f.where} ${f.detail}`).join('\n');
    const more=findings.length>8?`\n… and ${findings.length-8} more`:'';
    if(!confirm(`This file contains ${findings.length} action(s) that run programs, run commands or use the network:\n\n${listed}${more}\n\nOnly keep them if you trust the source.\nOK = import with these actions. Cancel = choose again.`)){
      if(!confirm('Import without those actions? Commands, web requests, program launches and automatic rules are removed.'))return;
      const safe=await api('command/sanitize',{config:bundle});data.profiles=safe.config.profiles;data.triggers=safe.config.triggers;
    }
  }
  if(data.assets){const replacements={};for(const [id,image] of Object.entries(data.assets)){const result=await api('image',{data:image});replacements[id]=result.id;}const visit=value=>{if(Array.isArray(value))value.forEach(visit);else if(value&&typeof value==='object')for(const [key,item] of Object.entries(value)){if(key==='icon'&&replacements[item])value[key]=replacements[item];else visit(item);}};delete data.assets;visit(data);}
  const previous=clone(config);remember();config=data;
  try {ensureSelection();const error=draftError();if(error)throw new Error(error);version++;dirty=true;await save();renderAll();toast('The configuration was imported.');}
  catch(error){config=previous;history.pop();renderAll();throw error;}
}
async function command(name,data={}) {const result=await api('command/'+name,data);if(result.message)toast(result.message);await pollStatus();}
function titleCase(value) { return String(value).replace(/(^|[ _\/-])([a-z])/g, (m, p, c) => p + c.toUpperCase()); }
function renderStatus() {
  const connected=dashboard.device?.connected;
  $('#led').classList.toggle('connected',!!connected);$('#led').classList.toggle('waiting',dashboard.running&&!connected);
  const context=[dashboard.device?.profile,dashboard.device?.page].filter(Boolean).join(' / ');
  $('#connection').textContent=connected?[dashboard.device.port,context].filter(Boolean).join(' · '):dashboard.running?(dashboard.connection||'Waiting for the device'):'The host has stopped';
  $('#connection').title=dashboard.device?.error||'';
  $('#host-toggle').hidden=!!dashboard.running;
  $('#screen-profile').textContent=profile.toUpperCase();$('#screen-page').textContent=titleCase(page);
  $('#screen-usb').textContent=connected?'PC CONNECTED':'NO PC';$('.screen-pill')?.classList.toggle('offline',!connected);
  const last=dashboard.device?.last_action;
  if(last?.at>lastActionAt){if(lastActionAt)toast(`${last.ok?'✓':'✕'} ${last.label}${last.error?' · '+last.error:''}`);lastActionAt=last.at;}
  document.title=connected&&context?`Tessera · ${context}`:'Tessera';
  followDevice();
  const usesStats=visibleButtons().some(b=>[b,...(b.states||[])].some(v=>v.label?.includes('$(stat:')));
  const live=JSON.stringify([deviceShowsSelection()?dashboard.device?.gauges||{}:{},dashboard.vars||{},dashboard.agents||{},usesStats?dashboard.stats||{}:{}]);
  if(live!==lastLive){lastLive=live;renderGrid();}
}
let lastLive='';
async function pollStatus() {try{dashboard=await api('status');renderStatus();}catch(error){$('#connection').textContent='The editor is disconnected';$('#led').classList.remove('connected');}}
document.addEventListener('keydown',event=>{
  if(recording){event.preventDefault();event.stopPropagation();if(event.key==='Escape'){recording.button.textContent='⌨ Record hotkey';recording.button.classList.remove('recording');recording=null;return;}
    if(['Control','Shift','Alt','Meta'].includes(event.key))return;
    const aliases={' ':'space',Escape:'esc',ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Delete:'delete',PageUp:'pageup',PageDown:'pagedown','/':'slash','`':'grave'};
    const parts=[event.ctrlKey?'ctrl':null,event.altKey?'alt':null,event.shiftKey?'shift':null,event.metaKey?'win':null,aliases[event.key]||event.key.toLowerCase()].filter(Boolean);
    const value=parts.join('+'),index=recording.index;recording=null;editAction(index,'keys',value);renderInspector();return;
  }
  const menu=$('#key-menu');
  if(!menu.hidden){const items=[...menu.querySelectorAll('[role="menuitem"]')],at=items.indexOf(document.activeElement);
    if(event.key==='Escape'){event.preventDefault();hideKeyMenu(true);return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?items.length-1:(at+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next].focus();return;}}
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().then(()=>toast('All changes are saved.')).catch(showError);return;}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||$('#form-dialog').open||$('#icon-dialog').open)return;
  const onDeck=!document.activeElement||document.activeElement===document.body||document.activeElement.closest('#deck-grid');
  if((event.key==='Delete'||event.key==='Backspace')&&onDeck&&current()){event.preventDefault();clearButton();toast(`Button ${selected} was cleared. Press Ctrl+Z to undo.`);return;}
  if((event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')&&current()){event.preventDefault();openKeyMenu(selected);return;}
  if(event.ctrlKey||event.metaKey) {const key=event.key.toLowerCase();if(['z','y','c','v','d'].includes(key)){event.preventDefault();if(key==='z')undo(event.shiftKey);if(key==='y')undo(true);if(key==='c')copyButton();if(key==='v')pasteButton();if(key==='d')duplicateButton();}}
});
function hideKeyMenu(restore=false) {$('#key-menu').hidden=true;if(restore)keyMenuReturnFocus?.focus();keyMenuReturnFocus=null;}
function openKeyMenu(id,x,y) {
  let tile=$(`[data-slot="${id}"]`);if(!tile||!visibleButtons().some(b=>b.id===id))return;
  selected=id;editState=0;renderGrid();renderInspector();tile=$(`[data-slot="${id}"]`);keyMenuReturnFocus=tile;
  const menu=$('#key-menu'),pinned=config.profiles[profile].pinned?.some(b=>b.id===id);
  menu.querySelector('[data-menu="pin"]').textContent=pinned?'Unpin from all pages':'Pin to all pages';menu.hidden=false;
  const rect=tile.getBoundingClientRect(),width=menu.offsetWidth,height=menu.offsetHeight;
  menu.style.left=Math.max(8,Math.min(x??rect.left+rect.width/2,window.innerWidth-width-8))+'px';
  menu.style.top=Math.max(8,Math.min(y??rect.top+rect.height/2,window.innerHeight-height-8))+'px';
  menu.querySelector('[role="menuitem"]').focus();
}
function showKeyMenu(event) {const tile=event.target.closest('[data-slot]');if(!tile)return;event.preventDefault();openKeyMenu(Number(tile.dataset.slot),event.clientX,event.clientY);}
document.addEventListener('contextmenu',showKeyMenu);
document.addEventListener('pointerdown',event=>{if(!event.target.closest('#key-menu'))hideKeyMenu(false);},true);
window.addEventListener('blur',()=>hideKeyMenu(false));window.addEventListener('resize',()=>hideKeyMenu(false));document.addEventListener('scroll',()=>hideKeyMenu(false),true);
// Pointer-based dragging keeps mouse and touch behavior identical, including
// embedded browser windows where native HTML drag/drop can be intercepted.
document.addEventListener('pointerdown',event=>{
  if(event.button!==0||!config)return;
  const source=event.target.closest('[data-slot],[data-action],[data-step],[data-program]');if(!source)return;
  if(source.dataset.step!==undefined&&event.target.closest('input,select,textarea,button,label'))return;
  if(source.dataset.slot&&!visibleButtons().some(b=>b.id===Number(source.dataset.slot)))return;
  drag={source,x:event.clientX,y:event.clientY,id:event.pointerId,active:false,ghost:null};
  source.setPointerCapture(event.pointerId);
});
document.addEventListener('pointermove',event=>{
  if(!drag||drag.id!==event.pointerId)return;
  if(!drag.active&&Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<7)return;
  if(!drag.active){drag.active=true;drag.ghost=text('div',drag.source.dataset.slot?'Move button '+drag.source.dataset.slot:drag.source.dataset.label||drag.source.innerText.split('\n')[0],'drag-ghost');document.body.append(drag.ghost);document.body.classList.add('dragging');if(drag.source.dataset.program!==undefined)$('#program-dialog').classList.add('drag-through');}
  drag.ghost.style.left=(event.clientX+15)+'px';drag.ghost.style.top=(event.clientY+15)+'px';
  document.querySelectorAll('.drag-over').forEach(n=>n.classList.remove('drag-over'));
  document.elementFromPoint(event.clientX,event.clientY)?.closest(drag.source.dataset.step!==undefined?'[data-step]':'[data-slot]')?.classList.add('drag-over');
});
function endDrag(event,cancel=false) {
  if(!drag||drag.id!==event.pointerId)return;
  const value=drag;drag=null;value.ghost?.remove();document.body.classList.remove('dragging');$('#program-dialog').classList.remove('drag-through');document.querySelectorAll('.drag-over').forEach(n=>n.classList.remove('drag-over'));
  if(!value.active||cancel)return;
  suppressClick=true;setTimeout(()=>suppressClick=false,0);
  const target=document.elementFromPoint(event.clientX,event.clientY);
  const slot=Number(target?.closest('[data-slot]')?.dataset.slot);
  if(value.source.dataset.program!==undefined&&slot){const program=installedPrograms[Number(value.source.dataset.program)];if(program)installProgram(program.target,slot).catch(showError);}
  else if(value.source.dataset.action&&slot)addAction(value.source.dataset.action,slot);
  else if(value.source.dataset.slot&&slot)moveSlot(Number(value.source.dataset.slot),slot);
  else if(value.source.dataset.step!==undefined){const step=target?.closest('[data-step]');if(step){const from=Number(value.source.dataset.step),to=Number(step.dataset.step);if(from!==to)mutate(()=>{const a=activeActions();a.splice(to,0,a.splice(from,1)[0]);});}}
}
document.addEventListener('pointerup',event=>endDrag(event));
document.addEventListener('pointercancel',event=>endDrag(event,true));
document.addEventListener('click',event=>{if(suppressClick){event.preventDefault();event.stopImmediatePropagation();}},true);
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
async function start() {
  const token=location.hash.slice(1);
  if(token){const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Deck-Token':token},body:'{}'});if(!response.ok)throw new Error('Open the program with Tessera.cmd.');window.history.replaceState(null,'',location.pathname);}
  const state=await api('config');config=state.config;revision=state.revision;profile=config.default_profile||Object.keys(config.profiles)[0];page=Object.keys(config.profiles[profile].pages)[0];
  try{const [,catalog]=await Promise.all([loadIconPack(),api('action-packs')]);actionCatalog=catalog;}catch(error){toast('The add-on packs could not be loaded. '+error.message);}
  renderAll();renderLibrary();setSaveState('✓ Configuration ready');await pollStatus();
  $('#profile').onchange=()=>{profile=$('#profile').value;page=Object.keys(config.profiles[profile].pages)[0];selected=1;editState=0;renderAll();syncPanel();};
  $('#action-search').oninput=renderLibrary;$('#undo').onclick=()=>undo();$('#redo').onclick=()=>undo(true);
  $('#icons-close').onclick=()=>$('#icon-dialog').close();
  $('#programs-close').onclick=()=>$('#program-dialog').close();
  $('#program-browse').onclick=async()=>{try{const result=await api('command/pick',{kind:'program'});if(result.target)placeProgram(result);}catch(error){showError(error);}};
  $('#program-search').oninput=renderProgramResults;
  $('#program-dialog').onclose=()=>{dialogReturnFocus?.focus();dialogReturnFocus=null;};
  $('#icon-dialog').onclose=()=>{iconReturnFocus?.focus();iconReturnFocus=null;};
  $('#form-dialog').onclose=()=>{dialogReturnFocus?.focus();dialogReturnFocus=null;};
  $('#icon-search').oninput=$('#icon-category').onchange=()=>{iconPage=0;renderIconResults();};
  $('#icons-prev').onclick=()=>{if(iconPage>0){iconPage--;renderIconResults();}};
  $('#icons-next').onclick=()=>{iconPage++;renderIconResults();};
  $('#new-page').onclick=()=>newPage();$('#page-options').onclick=pageSettings;$('#profile-options').onclick=profileSettings;
  $('#duplicate-page').onclick=duplicatePage;$('#duplicate-profile').onclick=duplicateProfile;$('#app-settings').onclick=appSettings;
  $('#key-menu').onclick=event=>{const action=event.target.closest('[data-menu]')?.dataset.menu;if(!action)return;hideKeyMenu();if(action==='duplicate')duplicateButton();if(action==='copy')copyButton();if(action==='pin')togglePin();if(action==='clear')clearButton();if(action==='test')testButton(selected).catch(showError);};
  $('#profile-templates').onclick=openTemplates;
  $('#new-profile').onclick=()=>dialog('New profile',[{name:'name',label:'Profile name',required:true}],values=>{const name=values.name.trim();if(!name||config.profiles[name])throw new Error('Choose a new profile name.');mutate(()=>{config.profiles[name]={match:[],pages:{Main:[]}};profile=name;page='Main';});renderAll();});
  $('#export').onclick=()=>exportConfig().catch(showError);$('#import').onclick=()=>$('#import-file').click();$('#import-file').onchange=async()=>{try{await importConfig($('#import-file').files[0]);}catch(error){showError(error);}$('#import-file').value='';};
  $('#activate').onclick=async()=>{try{await save();if(!dashboard.running)await api('command/start',{});await command('activate',{profile,page});}catch(error){showError(error);}};
  $('#host-toggle').onclick=async()=>{const b=$('#host-toggle');b.disabled=true;try{await command('start');}catch(error){showError(error);}finally{b.disabled=false;}};
  $('#reload').onclick=async()=>{if(dirty&&!confirm('Discard unsaved changes and reload the configuration from disk?'))return;try{const state=await api('config');config=state.config;revision=state.revision;dirty=false;conflicted=false;history=[];future=[];$('#reload').hidden=true;renderAll();setSaveState('✓ Configuration reloaded');}catch(error){showError(error);}};
  setupMoreMenu();fitDevice();window.addEventListener('resize',fitDevice);tickClock();setInterval(tickClock,10000);
  $('#sync').onchange=()=>{if($('#sync').checked)syncPanel();};
  pollStatus();setInterval(pollStatus,1500);
}
start().catch(error=>{setSaveState('The editor could not start',error.message);toast(error.message);});

/* Brand: the 3x3 mosaic mark and the tile wordmark, identical to the device header. */
function brandColor(t) {
  const stops = [[88, 224, 155], [77, 208, 225], [179, 136, 255]];
  const scaled = Math.min(Math.max(t, 0), 1) * 2, i = Math.min(Math.floor(scaled), 1), f = scaled - i;
  return `rgb(${stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * f)).join(',')})`;
}
function brandTile(parent, x, y, size, radius, color) {
  const tile = document.createElement('i');
  tile.style.cssText = `left:${x}px;top:${y}px;width:${size}px;height:${size}px;border-radius:${radius}px;background:${color}`;
  parent.append(tile);
}
function mountBrand() {
  const glyphs = {
    T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
    E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
    S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
    R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
    A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001']
  };
  document.querySelectorAll('[data-logo]').forEach(el => {
    for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
      if (row === 0 && col === 2) continue;
      brandTile(el, col * 16, 4 + row * 16, 13, 4, brandColor((row + col) / 4));
    }
    brandTile(el, 34, 0, 12, 4, '#ffb74d');
  });
  document.querySelectorAll('[data-wordmark]').forEach(el => {
    [...'TESSERA'].forEach((letter, n) => glyphs[letter].forEach((line, row) => [...line].forEach((bit, col) => {
      if (bit === '1') brandTile(el, n * 22 + col * 4, row * 4, 3, 1, brandColor((n * 5 + col) / 34));
    })));
  });
}
mountBrand();

/* Panel firmware: list verified packages, install with progress. */
let firmwareTimer = null;
async function openFirmware() {
  $('#more-menu').hidden = true;
  $('#firmware-dialog').showModal();
  try { await refreshFirmware(); } catch (error) { showError(error); }
}
async function refreshFirmware() {
  const info = await api('command/firmware-list', {});
  const select = $('#firmware-package'), good = info.packages.filter(p => !p.error);
  select.replaceChildren();
  for (const p of good) select.append(element('option', {value: p.path, text: `Version ${p.version} · ${Math.round(p.bytes / 1024)} KiB`}));
  for (const p of info.packages.filter(item => item.error)) select.append(element('option', {value: '', disabled: 'true', text: `${p.path.split(/[\\/]/).pop()} · ${p.error}`}));
  if (!info.packages.length) select.append(element('option', {value: '', text: 'No package found in dist/ or firmware/'}));
  const device = info.device;
  $('#firmware-device').textContent = device.connected
    ? `Panel connected · firmware ${device.firmware || 'unknown'} · protocol ${device.protocol ?? '?'} · Tessera ${info.host || '?'}`
    : `The panel is not connected · Tessera ${info.host || '?'}`;
  $('#firmware-install').disabled = !good.length;
  if (info.job.state === 'running') pollFirmware();
}
async function installFirmware() {
  const path = $('#firmware-package').value;
  if (!path || !confirm('Write the firmware now? Do not unplug the panel until it has finished.')) return;
  try { await api('command/firmware-install', {package: path, mode: $('#firmware-mode').value, force: $('#firmware-force').checked}); }
  catch (error) { showError(error); return; }
  pollFirmware();
}
async function pollFirmware() {
  clearTimeout(firmwareTimer);
  $('.firmware-progress').hidden = false;
  let job;
  try { job = (await api('command/firmware-progress', {})).job; } catch (error) { showError(error); return; }
  $('#firmware-bar').value = job.percent || 0;
  const label = $('#firmware-state');
  if (job.state === 'running') {
    label.textContent = `${job.stage === 'checking' ? 'Checking the panel' : 'Writing'} … ${job.percent || 0}%`;
    firmwareTimer = setTimeout(pollFirmware, 700);
  } else if (job.state === 'done') {
    label.textContent = `Installed ${job.result.installed}${job.result.previous ? ` (was ${job.result.previous})` : ''}. The host has started again.`;
  } else if (job.state === 'failed') {
    label.textContent = job.error || 'The installation failed.';
    $('.firmware-force').hidden = !(job.error || '').includes('did not answer');
  }
  $('#firmware-install').disabled = job.state === 'running';
}
$('#firmware-open').onclick = openFirmware;
$('#firmware-close').onclick = () => $('#firmware-dialog').close();
$('#firmware-install').onclick = installFirmware;

/* Key colors: an own background, label color and outline per button (or per state of a toggle button). */
function renderStyle(panel) {
  const row = (label, key, fallback) => {
    const input = element('input', {type: 'color', value: appearance()[key] || fallback, 'aria-label': label});
    input.addEventListener('input', () => mutate(() => { appearance()[key] = input.value.toUpperCase(); }, false, editKey('style', key)));
    return element('div', {class: 'appearance-row'}, text('span', label, 'hint'), input,
      button('Default', () => mutate(() => { delete appearance()[key]; }), 'text-button'));
  };
  panel.append(element('details', {class: 'quick-icons'}, text('summary', 'Key colors'),
    row('Background', 'bg', '#172329'), row('Label text', 'text_color', '#E8F4EF'), row('Outline', 'border', '#31444D')));
}

/* Test mode: what pressing a key would do, explained by the host without running anything. */
async function testButton(id = selected) {
  const base = visibleButtons().find(b => b.id === id);
  if (!base) return toast('Choose a key with an action first.');
  const holder = base.states ? base.states[id === selected ? Math.min(editState, base.states.length - 1) : 0] : base;
  const payload = {actions: clone(holder.actions || [])};
  if (base.hold_actions?.length) payload.hold_actions = clone(base.hold_actions);
  const result = await api('command/dryrun', payload);
  const box = $('#test-steps');
  box.replaceChildren();
  $('#test-title').textContent = `Test: ${resolveLabel(holder.label || base.label) || `key ${id}`}`;
  const section = (title, report) => {
    box.append(text('h3', title));
    if (!report.steps.length) box.append(text('p', 'No actions.', 'hint'));
    for (const step of report.steps) box.append(element('div', {class: `test-step ${step.ok ? 'ok' : 'bad'}`}, text('span', step.ok ? '✓' : '✕', 'test-mark'), text('span', `${step.index}. ${step.text}`)));
    if (report.wait_seconds) box.append(text('p', `Waits ${report.wait_seconds} s in total.`, 'hint'));
  };
  section('When pressed', result.actions || {steps: [], wait_seconds: 0});
  if (result.hold_actions) section('When held', result.hold_actions);
  $('#test-dialog').showModal();
}

/* Ambient screen: a big clock (and optional weather) when the panel is idle. */
function ambientSettings() {
  $('#more-menu').hidden = true;
  const ambient = {enabled: false, after: 120, ...(config.ambient || {})}, weather = ambient.weather;
  const afterChoices = [30, 60, 120, 300, 600].map(v => [String(v), v < 60 ? `${v} seconds` : `${v / 60} min`]);
  if (!afterChoices.some(([v]) => Number(v) === ambient.after)) afterChoices.push([String(ambient.after), `${ambient.after} seconds`]);
  const where = weather ? `Currently ${weather.name} in ${weather.unit === 'fahrenheit' ? 'Fahrenheit' : 'Celsius'}. ` : '';
  dialog('Ambient screen', [
    {name: 'enabled', label: 'Show a big clock when the panel has been idle', type: 'checkbox', value: ambient.enabled, note: 'Touch the panel to get your keys back. Needs the firmware that ships with this version.'},
    {name: 'after', label: 'Show it after', options: afterChoices, value: String(ambient.after)},
    {name: 'city', label: 'Weather for (city, optional)', value: weather?.name || '', note: `${where}Weather comes from open-meteo.com every 15 minutes. Leave the city empty for no weather and no internet use.`},
    {name: 'unit', label: 'Temperature unit', options: [['celsius', 'Celsius'], ['fahrenheit', 'Fahrenheit']], value: weather?.unit || 'celsius'}
  ], values => {
    const city = values.city.trim(), keep = weather && weather.name === city;
    mutate(() => {
      config.ambient = {enabled: values.enabled, after: Number(values.after)};
      if (keep) config.ambient.weather = {...weather, unit: values.unit};
    });
    if (city && !keep) lookupCity(city, values.unit).catch(showError);
  }, 'Apply');
}
async function lookupCity(city, unit) {
  const {places} = await api('command/weather-search', {query: city});
  if (!places.length) throw new Error(`No place called “${city}” was found.`);
  const place = places[0];
  mutate(() => { config.ambient = {...(config.ambient || {enabled: true, after: 120}), weather: {name: place.name, latitude: place.latitude, longitude: place.longitude, unit}}; });
  toast(`Weather for ${[place.name, place.region, place.country].filter(Boolean).join(', ')}.`);
}

/* Images: crop still pictures to the square the key shows; animations are sent as they are. */
async function chooseImage(file, id = selected) {
  if (!file) return;
  if (file.type === 'image/gif' || file.type === 'image/webp') return uploadImage(file, id);
  const bitmap = await createImageBitmap(file);
  const blob = await openCropper(bitmap);
  bitmap.close?.();
  if (!blob) return;
  await uploadImage(new File([blob], `${file.name.replace(/\.[^.]+$/, '')}.png`, {type: 'image/png'}), id);
}
function openCropper(bitmap) {
  return new Promise(resolve => {
    const view = $('#crop-dialog'), canvas = $('#crop-canvas'), context = canvas.getContext('2d'), zoom = $('#crop-zoom');
    const size = canvas.width, cover = Math.max(size / bitmap.width, size / bitmap.height), stop = new AbortController();
    let scale = 1, x = (size - bitmap.width * cover) / 2, y = (size - bitmap.height * cover) / 2, drag = null, answer = null;
    const clamp = () => {
      const w = bitmap.width * cover * scale, h = bitmap.height * cover * scale;
      x = Math.min(0, Math.max(size - w, x));
      y = Math.min(0, Math.max(size - h, y));
    };
    const draw = () => {
      clamp();
      context.fillStyle = '#091014';
      context.fillRect(0, 0, size, size);
      context.drawImage(bitmap, x, y, bitmap.width * cover * scale, bitmap.height * cover * scale);
    };
    const setZoom = value => {
      const w = bitmap.width * cover * scale, h = bitmap.height * cover * scale, cx = (size / 2 - x) / w, cy = (size / 2 - y) / h;
      scale = Math.min(4, Math.max(1, value));
      x = size / 2 - cx * bitmap.width * cover * scale;
      y = size / 2 - cy * bitmap.height * cover * scale;
      zoom.value = String(Math.round(scale * 100));
      draw();
    };
    const finish = blob => { answer = blob; view.close(); };
    canvas.addEventListener('pointerdown', event => { drag = {px: event.clientX, py: event.clientY, x, y}; canvas.setPointerCapture(event.pointerId); }, {signal: stop.signal});
    canvas.addEventListener('pointermove', event => { if (!drag) return; const k = size / canvas.getBoundingClientRect().width; x = drag.x + (event.clientX - drag.px) * k; y = drag.y + (event.clientY - drag.py) * k; draw(); }, {signal: stop.signal});
    canvas.addEventListener('pointerup', () => { drag = null; }, {signal: stop.signal});
    canvas.addEventListener('wheel', event => { event.preventDefault(); setZoom(scale + (event.deltaY < 0 ? .1 : -.1)); }, {signal: stop.signal, passive: false});
    zoom.addEventListener('input', () => setZoom(Number(zoom.value) / 100), {signal: stop.signal});
    $('#crop-cancel').addEventListener('click', () => finish(null), {signal: stop.signal});
    $('#crop-use').addEventListener('click', () => {
      const out = document.createElement('canvas'), k = 144 / size;
      out.width = out.height = 144;
      out.getContext('2d').drawImage(bitmap, x * k, y * k, bitmap.width * cover * scale * k, bitmap.height * cover * scale * k);
      out.toBlob(blob => finish(blob), 'image/png');
    }, {signal: stop.signal});
    view.addEventListener('close', () => { stop.abort(); resolve(answer); }, {once: true});
    zoom.value = '100';
    draw();
    view.showModal();
  });
}

/* Online icons (Iconify): searched and fetched by the host only when the user asks. */
async function iconifySearch() {
  const query = $('#iconify-query').value.trim(), box = $('#iconify-results');
  $('#iconify-note').hidden = false;
  box.hidden = false;
  box.replaceChildren(text('p', 'Searching …', 'hint'));
  const {icons} = await api('command/iconify-search', {query});
  box.replaceChildren();
  if (!icons.length) { box.append(text('p', 'Nothing found online.', 'hint')); return; }
  const queue = [...icons];
  const load = async () => {
    while (queue.length) {
      const id = queue.shift(), item = button('', () => useOnlineIcon(id).catch(showError), 'icon-choice online', id);
      box.append(item);
      try {
        const {svg} = await api('command/iconify-svg', {id, color: '#FFFFFF'});
        item.replaceChildren(element('img', {src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, alt: id, width: '36', height: '36'}));
      } catch { item.textContent = '?'; }
    }
  };
  await Promise.all([load(), load(), load(), load()]);
}
async function useOnlineIcon(id) {
  const {svg} = await api('command/iconify-svg', {id, color: (appearance()?.color || '#FFFFFF').toUpperCase()});
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 144;
  canvas.getContext('2d').drawImage(image, 0, 0, 144, 144);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  await uploadImage(new File([blob], `${id.replace(':', '-')}.png`, {type: 'image/png'}));
  $('#icon-dialog').close();
}
/* Backups: the host keeps rotating copies of profiles.json; any of them can be put back. */
async function openBackups() {
  $('#more-menu').hidden = true;
  const {backups} = await api('command/backups', {}), list = $('#backup-list');
  list.replaceChildren();
  if (!backups.length) list.append(text('p', 'No backups yet. The first one is made when you change something.', 'hint'));
  for (const item of backups) {
    list.append(element('div', {class: 'backup-row'},
      element('div', {}, text('strong', item.saved), text('small', `${item.profiles} profiles · ${item.buttons} keys · ${Math.max(1, Math.round(item.bytes / 1024))} KiB`)),
      button('Restore', () => restoreBackup(item).catch(showError), 'outline')));
  }
  $('#backup-dialog').showModal();
}
async function restoreBackup(item) {
  if (!confirm(`Replace the current configuration with the backup from ${item.saved}? The current one is kept as a backup.`)) return;
  const state = await api('command/restore-backup', {name: item.name});
  config = state.config; revision = state.revision;
  dirty = false; conflicted = false; history = []; future = [];
  $('#reload').hidden = true;
  $('#backup-dialog').close();
  renderAll();
  setSaveState('✓ Backup restored');
}
/* Updates and diagnostics: only when the user asks. */
async function checkUpdates() {
  const label = $('#firmware-latest');
  label.textContent = 'Checking GitHub …';
  const info = await api('command/update-check', {});
  $('#firmware-download').hidden = !(info.newer && info.firmware && info.sums);
  label.textContent = info.newer
    ? `Version ${info.latest} is available (you have ${info.current}).${info.firmware ? '' : ' It has no firmware package.'}`
    : `You have the latest version (${info.current}).`;
  if (info.newer) label.append(' ', element('a', {href: info.page, target: '_blank', rel: 'noopener', text: 'Release notes and the Windows program'}));
}
async function downloadFirmware() {
  const result = await api('command/update-download-firmware', {});
  toast(result.message);
  await refreshFirmware();
}
$('#firmware-check').onclick = () => checkUpdates().catch(error => { $('#firmware-latest').textContent = error.message; });
$('#firmware-download').onclick = () => downloadFirmware().catch(showError);
$('#diagnostics-export').onclick = async () => { $('#more-menu').hidden = true; try { await command('diagnostics'); } catch (error) { showError(error); } };
/* Plugins: turn integrations on and off and set their options; the host starts and stops them. */
async function openPlugins() {
  $('#more-menu').hidden = true;
  await renderPlugins();
  $('#plugins-dialog').showModal();
}
async function renderPlugins() {
  const {plugins, problems} = await api('command/plugins', {}), list = $('#plugins-list');
  list.replaceChildren();
  if (!plugins.length) list.append(text('p', 'No plugins installed. Put a plugin folder in the plugins folder next to Tessera.cmd.', 'hint'));
  for (const plugin of plugins) {
    const box = element('div', {class: 'plugin-row'});
    const toggle = element('label', {class: 'check-option'}, element('input', {type: 'checkbox'}), element('span', {},
      text('strong', `${plugin.name} ${plugin.version}`),
      text('small', `${plugin.enabled ? plugin.state : 'off'} · may use: ${plugin.permissions.join(', ') || 'nothing'}`)));
    const check = toggle.querySelector('input');
    check.checked = plugin.enabled;
    check.onchange = () => { setPlugin(plugin.id, {enabled: check.checked}); renderPlugins(); };
    box.append(toggle);
    if (plugin.error) box.append(text('p', plugin.error, 'error'));
    for (const [key, spec] of Object.entries(plugin.settings || {})) {
      const value = plugin.values[key] ?? spec.default ?? (spec.type === 'checkbox' ? false : '');
      if (spec.type === 'checkbox') {
        const option = element('label', {class: 'check-option'}, element('input', {type: 'checkbox'}), element('span', {}, text('strong', spec.label || key)));
        const input = option.querySelector('input');
        input.checked = !!value;
        input.onchange = () => setPlugin(plugin.id, {settings: {[key]: input.checked}});
        box.append(option);
      } else {
        box.append(field(spec.label || key, String(value), v => setPlugin(plugin.id, {settings: {[key]: spec.type === 'number' ? Number(v) : v}}), {type: spec.type === 'number' ? 'number' : 'text'}));
      }
    }
    list.append(box);
  }
  for (const problem of problems) list.append(text('p', problem, 'error'));
}
function setPlugin(id, change) {
  mutate(() => {
    config.plugins ??= {};
    const entry = config.plugins[id] ??= {enabled: false, settings: {}};
    if ('enabled' in change) entry.enabled = change.enabled;
    if (change.settings) entry.settings = {...entry.settings, ...change.settings};
  }, false);
}
$('#plugins-open').onclick = () => openPlugins().catch(showError);
$('#plugins-close').onclick = () => $('#plugins-dialog').close();
$('#backups-open').onclick = () => openBackups().catch(showError);
$('#backup-close').onclick = () => $('#backup-dialog').close();
$('#ambient-open').onclick = ambientSettings;
$('#test-close').onclick = () => $('#test-dialog').close();
$('#iconify-search').onclick = () => iconifySearch().catch(showError);
$('#iconify-query').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); iconifySearch().catch(showError); } });
