'use strict';
const $ = s => document.querySelector(s);
const clone = value => structuredClone(value);
const icons = {ok:'✓',close:'✕',settings:'⚙',home:'⌂',folder:'▱',download:'↓',refresh:'↻',play:'▶',pause:'Ⅱ',stop:'■',plus:'＋',minus:'−',loop:'↺',list:'☷',upload:'↑',bolt:'ϟ',bell:'♧',wifi:'◉',trash:'⌫',edit:'✎'};
const iconNames = {ok:'Hake',close:'Kryss',settings:'Innstillinger',home:'Hjem',folder:'Mappe',download:'Nedlasting',refresh:'Oppdater',play:'Spill',pause:'Pause',stop:'Stopp',plus:'Pluss',minus:'Minus',loop:'Gjenta',list:'Liste',upload:'Opplasting',bolt:'Lyn',bell:'Varsel',wifi:'Nettverk',trash:'Slett',edit:'Rediger'};
const kinds = {
  hotkey:{name:'Hurtigtast',icon:'bolt',field:'keys',label:'Tastekombinasjon',placeholder:'ctrl+shift+b',group:'På datamaskinen'},
  open:{name:'Åpne program / fil',icon:'folder',field:'target',label:'Program, fil eller nettadresse',placeholder:'Velg et program eller lim inn en sti',group:'På datamaskinen'},
  text:{name:'Skriv tekst',icon:'edit',field:'text',label:'Tekst som skal skrives',placeholder:'Skriv teksten her …',group:'På datamaskinen'},
  folder:{name:'Åpne mappe',icon:'folder',field:'page',label:'Mappe',group:'Navigasjon'},
  back:{name:'Tilbake',icon:'home',field:null,label:'Tilbake til forrige mappe',group:'Navigasjon'},
  page:{name:'Bytt side',icon:'folder',field:'page',label:'Gå til side',group:'Navigasjon'},
  profile:{name:'Bytt profil',icon:'list',field:'profile',label:'Gå til profil',group:'Navigasjon'},
  delay:{name:'Vent litt',icon:'pause',field:'ms',label:'Forsinkelse (millisekunder)',placeholder:'500',group:'Flere handlinger'},
  shell:{name:'Kjør kommando',icon:'settings',field:'command',label:'Kommando',placeholder:'Kommandoen kjøres når knappen trykkes',group:'Avansert'},
  http:{name:'HTTP-forespørsel',icon:'wifi',field:'url',label:'Adresse',placeholder:'https://…',group:'Avansert'},
  press:{name:'Aktiver en annen knapp',icon:'loop',field:'id',label:'Knappnummer (1–18)',group:'Avansert'},
  set:{name:'Sett variabel',icon:'edit',field:'variable',label:'Variabelnavn',group:'Avansert'},
  home:{name:'Gå hjem',icon:'home',field:null,label:'Gå til standardprofilens første side',group:'Navigasjon'},
};
const presets = [
  {name:'Lyd av / på',icon:'minus',keys:'volumemute'}, {name:'Volum ned',icon:'minus',keys:'volumedown'},
  {name:'Volum opp',icon:'plus',keys:'volumeup'}, {name:'Spill / pause',icon:'play',keys:'playpause'},
  {name:'Neste spor',icon:'refresh',keys:'medianext'}, {name:'Forrige spor',icon:'loop',keys:'mediaprev'},
  {name:'Kopier',icon:'list',keys:'ctrl+c'}, {name:'Lim inn',icon:'download',keys:'ctrl+v'},
  {name:'Skjermbilde',icon:'bolt',keys:'win+shift+s'}
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
  'Lyd og video':/audio|sound|volume|microphone|\bmic\b|music|speaker|headphone|video|camera|film|podcast|radio|play|pause/,
  'Filer og mapper':/file|folder|document|archive|clipboard|save|download|upload/,
  'Utvikling':/code|terminal|git|bug|database|braces|brackets|regex|binary|cpu/,
  'Nettverk':/network|wifi|ethernet|router|cloud|server|bluetooth|internet|globe|signal/,
  'Hjem og enheter':/house|home|light|lamp|bulb|plug|power|battery|monitor|keyboard|mouse|printer|phone|tablet|laptop|computer/,
  'Spill':/game|joystick|dice|sword|trophy|medal|target|crosshair|puzzle/,
  'Arbeid':/calendar|mail|briefcase|chart|presentation|clock|timer|alarm|notebook|contact|users|user|meeting/,
  'Piler og navigasjon':/arrow|chevron|navigation|move|map|route|compass|menu|panel|layout/
};
const norwegianSearch={mikrofon:['mic','microphone'],kamera:['camera'],lyd:['sound','audio','volume'],musikk:['music','headphones'],høyttaler:['speaker'],volum:['volume'],
  mappe:['folder'],fil:['file'],filer:['file'],lagre:['save'],spill:['game','joystick','dice'],innstillinger:['settings','sliders'],skjerm:['monitor','screen','display'],
  nettverk:['network','wifi','ethernet'],lys:['light','lamp','bulb'],hjem:['home','house'],pil:['arrow','chevron'],piler:['arrow','chevron'],
  epost:['mail','inbox'],epostadresse:['mail'],tid:['clock','timer'],klokke:['clock','watch'],lås:['lock'],søk:['search'],slett:['trash','delete'],
  strøm:['power','plug','battery'],telefon:['phone'],tastatur:['keyboard'],pause:['pause'],stopp:['stop','square'],start:['play','power'],
  opptak:['record','circle','video'],kode:['code','terminal'],verktøy:['tool','wrench','hammer'],arbeid:['briefcase','calendar','chart'],av:['off'],på:['on']};

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
  options($('#icon-category'),['Alle ikoner','Favoritter','Nylig brukt',...Object.keys(iconGroups)],'Alle ikoner');
  $('#icon-pack-info').textContent=`${value.count.toLocaleString('nb-NO')} ulike ikoner · ${value.name} ${value.version} · Ingen nettilkobling nødvendig`;
  renderGrid();renderInspector();
}
function saveIconPreferences() {api('icon-preferences',iconPreferences).catch(error=>toast('Ikonvalg er beholdt, men favorittlisten kunne ikke lagres: '+error.message));}
async function openIcons() {
  try {
    await loadIconPack();iconReturnFocus=document.activeElement;iconPage=0;$('#icon-search').value='';renderIconResults();$('#icon-dialog').showModal();$('#icon-search').focus();
  }catch(error){showError(error);}
}
function renderIconResults() {
  if(!iconPack)return;
  const query=$('#icon-search').value.trim().toLowerCase().replaceAll('-',' '),group=$('#icon-category').value;
  const terms=query.split(/\s+/).filter(Boolean).map(word=>[word,...(norwegianSearch[word]||[])]);
  let list=iconPack.icons.filter(item=>(group==='Alle ikoner'||group==='Favoritter'&&iconPreferences.favorites.includes(item.id)||group==='Nylig brukt'&&iconPreferences.recent.includes(item.id)||item.groups.includes(group))&&
    (!query||terms.every(alternatives=>alternatives.some(word=>word.length<=3?item.search.split(' ').includes(word):item.search.includes(word)))));
  if(group==='Nylig brukt')list.sort((a,b)=>iconPreferences.recent.indexOf(a.id)-iconPreferences.recent.indexOf(b.id));
  else list.sort((a,b)=>a.name.localeCompare(b.name));
  const pages=Math.max(1,Math.ceil(list.length/iconPageSize));iconPage=Math.min(iconPage,pages-1);
  const shown=list.slice(iconPage*iconPageSize,(iconPage+1)*iconPageSize),color=current()?.color||'#35D07F';
  $('#icon-results').replaceChildren(...shown.map(item=>{
    const selected=current()?.icon===item.id,favorite=iconPreferences.favorites.includes(item.id);
    const choose=button('',()=>{
      mutate(()=>{if(current())appearance().icon=item.id;});
      iconPreferences.recent=[item.id,...iconPreferences.recent.filter(id=>id!==item.id)].slice(0,24);saveIconPreferences();$('#icon-dialog').close();
    },'catalog-choice'+(selected?' selected':''),item.name);
    choose.setAttribute('aria-label','Velg ikon '+item.name);choose.setAttribute('aria-pressed',selected);
    choose.append(iconVisual(item.id,color,'catalog-symbol'),text('span',item.name,'catalog-name'));
    const star=button(favorite?'★':'☆',()=>{
      if(favorite)iconPreferences.favorites=iconPreferences.favorites.filter(id=>id!==item.id);
      else if(iconPreferences.favorites.length<512)iconPreferences.favorites.push(item.id);
      else return toast('Favorittlisten er full. Fjern et ikon først.');
      saveIconPreferences();renderIconResults();
    },'catalog-star'+(favorite?' favorite':''),favorite?'Fjern favoritt':'Legg til favoritt');
    star.setAttribute('aria-label',(favorite?'Fjern favoritt ':'Favoritt ')+item.name);star.setAttribute('aria-pressed',favorite);
    return element('div',{class:'catalog-item'},choose,star);
  }));
  if(!shown.length)$('#icon-results').append(text('p',group==='Favoritter'?'Trykk ☆ på et ikon for å legge det i favoritter.':'Ingen treff. Prøv et annet ord eller en annen kategori.','hint icon-empty'));
  $('#icon-count').textContent=list.length?`${iconPage*iconPageSize+1}–${Math.min(list.length,(iconPage+1)*iconPageSize)} av ${list.length.toLocaleString('nb-NO')} ikoner`:'0 treff';
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
  if(!response.ok) {const error=new Error(result.error||'Operasjonen feilet');error.status=response.status;throw error;}
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
function uniqueName(base,names) {let name=`${base} kopi`,number=2;while(names.includes(name))name=`${base} kopi ${number++}`;return name;}
function clearButton() {if(!current())return;mutate(()=>{const list=owner(),at=list.findIndex(x=>x.id===selected);if(at>=0)list.splice(at,1);});}
function duplicateButton() {
  const source=current(),slot=Array.from({length:18},(_,i)=>i+1).find(id=>!visibleButtons().some(b=>b.id===id));
  if(!source)return;if(!slot)return toast('Denne siden har ingen ledige spor.');
  mutate(()=>{buttons().push({...clone(source),id:slot});selected=slot;editState=0;});
  toast(`Knappen er duplisert til spor ${slot}.`);
}
function duplicateProfile() {
  const name=uniqueName(profile,Object.keys(config.profiles));
  mutate(()=>{config.profiles[name]=clone(config.profiles[profile]);profile=name;page=Object.keys(config.profiles[name].pages)[0];selected=1;editState=0;});
  renderAll();toast(`Profilen «${name}» er opprettet.`);
}
function duplicatePage() {
  const pages=config.profiles[profile].pages,name=uniqueName(page,Object.keys(pages));
  mutate(()=>{pages[name]=clone(pages[page]);page=name;selected=1;editState=0;});
  renderAll();toast(`Siden «${name}» er opprettet.`);
}
async function uploadImage(file,id=selected) {if(!file)return;if(file.size>8*1024*1024)throw new Error('Bruk et bilde på høyst 8 MB');const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let at=0;at<bytes.length;at+=16384)binary+=String.fromCharCode(...bytes.subarray(at,at+16384));const result=await api('image',{data:btoa(binary)});mutate(()=>{selected=id;if(!current())buttons().push({id,label:file.name.replace(/\.[^.]+$/,''),icon:'ok',color:'#35D07F',actions:[]});appearance().icon=result.id;});if(result.sampled)toast('Animasjonen er tilpasset til 12 bilder for panelet.');}

function setSaveState(message,note='Endringer lagres automatisk.') {$('#save-state').textContent=message;$('#save-note').textContent=note;}
function draftError() {
  for(const item of Object.values(config.profiles)) for(const b of profileButtons(item)) {
    if(!b.label?.trim()) return 'Gi knappen et navn';
    for(const holder of [b,...(b.states||[])]) for(const a of holder.actions||[]) {
      const kind=kinds[a.type];
      if(!kind) return 'Ukjent handling';
      if(kind.field && a.type!=='text' && (a[kind.field]===undefined || String(a[kind.field]).trim()==='')) return 'Fyll inn '+kind.label.toLowerCase();
    }
  }
  return '';
}
function remember() {history.push(clone(config));if(history.length>60)history.shift();future=[];}
function changed() {
  dirty=true;version++;clearTimeout(saveTimer);renderGrid();updateHistory();
  const error=draftError();setSaveState(error?'Utkast · '+error:'Lagrer …',error?'Fyll ut feltet, eller angre endringen.':'Endringen sendes automatisk til den aktive siden.');
  if(!error&&!conflicted)saveTimer=setTimeout(()=>save().catch(showError),650);
}
function mutate(fn,refresh=true) {remember();fn();changed();if(refresh)renderInspector();}
function showError(error) {setSaveState('Ikke lagret',error.message);toast(error.message);if(error.status===409){conflicted=true;$('#reload').hidden=false;}}
async function save() {
  clearTimeout(saveTimer);
  if(saveInFlight){await saveInFlight;if(dirty)return save();return;}
  if(!dirty) return;
  const invalid=draftError();if(invalid)throw new Error(invalid);
  if(conflicted)throw new Error('Last inn oppsettet på nytt for å løse konflikten.');
  saving=true;const sentVersion=version;
  try {
    saveInFlight=api('config',{config:clone(config),revision});
    const result=await saveInFlight;revision=result.revision;
    if(version===sentVersion){dirty=false;const same=dashboard.device?.profile===profile&&dashboard.device?.page===page;
      setSaveState('✓ Lagret på PC-en',dashboard.device?.connected?(same?'Denne siden er oppdatert på panelet.':`Panelet viser ${dashboard.device.profile} / ${dashboard.device.page}. Trykk «Vis på enheten» for å bytte.`):'Koble til panelet og start verten for å synkronisere.');}
  } finally {saving=false;saveInFlight=null;}
  if(dirty)saveTimer=setTimeout(()=>save().catch(showError),200);
}
function updateHistory() {$('#undo').disabled=!history.length;$('#redo').disabled=!future.length;}
function undo(redo=false) {const source=redo?future:history,target=redo?history:future;if(!source.length)return;target.push(clone(config));config=source.pop();ensureSelection();changed();renderAll();}
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
    const item=button(name,()=>{page=name;selected=1;editState=0;renderAll();},'page-chip'+(page===name?' active':''));
    item.setAttribute('aria-current',page===name?'page':'false');return item;
  }));
}
function renderGrid() {
  const grid=$('#deck-grid');const focused=document.activeElement?.dataset.slot;
  grid.replaceChildren(...Array.from({length:18},(_,index)=>{
    const id=index+1,base=visibleButtons().find(b=>b.id===id),b=base&&{...base,...(id===selected?appearance(base):base.states?.[0]||{})};
    const tile=element('button',{class:'deck-key'+(!b?' empty':'')+(id===selected?' selected':''),type:'button',draggable:'false',
      'data-slot':id,'aria-label':`Knapp ${id}: ${b?.label||'Tomt spor'}`,'aria-pressed':id===selected,
      onclick:()=>{selected=id;editState=0;renderGrid();renderInspector();}},
      text('span',String(id),'slot-number'),b?iconVisual(b.icon,b.color,'key-symbol'):text('span','＋','key-symbol'),text('span',b?.label||'','key-label'));
    tile.style.setProperty('--key-color',b?.color||'#92edba');
    if(base&&config.profiles[profile].pinned?.includes(base))tile.append(text('span','◆','pin-badge'));
    if(b?.title){const name=tile.querySelector('.key-label');name.style.fontSize=(b.title.size||16)*.65+'px';name.style.fontWeight=b.title.bold?'700':'400';name.hidden=b.title.position==='hidden';name.classList.add('title-'+(b.title.position||'bottom'));}
    tile.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
    tile.addEventListener('drop',event=>{if(event.dataTransfer.files.length){event.preventDefault();uploadImage(event.dataTransfer.files[0],id).catch(showError);}});
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
function actionTemplate(key) {
  if(key.startsWith('pack:')) {const pack=actionCatalog.packs[Number(key.split(':')[1])];if(!pack)return;return {label:pack.name,icon:pack.icon||'ok',color:pack.color||'#35D07F',actions:clone(pack.actions)};}
  if(key.startsWith('preset:')) {const preset=presets[Number(key.split(':')[1])];if(!preset)return;return {label:preset.name,icon:preset.icon,actions:[{type:'hotkey',keys:preset.keys}]};}
  const k=kinds[key];if(!k)return;
  const value={hotkey:'',text:'',open:'',folder:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,back:null,page:Object.keys(config.profiles[profile].pages).find(p=>p!==page)||page,
    profile:Object.keys(config.profiles).find(p=>p!==profile)||profile,delay:500,shell:'',http:'',press:1,set:''}[key];
  const action={type:key,...(k.field?{[k.field]:value}:{}),...(key==='http'?{method:'GET'}:{})};
  return {label:k.name,icon:k.icon,actions:[action]};
}
function addAction(key,id=selected) {
  const item=actionTemplate(key);if(!item)return;
  mutate(()=>{selected=id;let b=current();if(!b){b={id,label:item.label,icon:item.icon,color:item.color||'#35D07F',actions:[]};buttons().push(b);}b.actions??=[];activeActions().push(...clone(item.actions));});
  toast(activeActions().length>1?'Handling lagt til. Trinnene kjøres ovenfra og ned.':'Handling lagt til. Tilpass innstillingene til høyre.');
}
function renderLibrary() {
  const search=$('#action-search').value.toLocaleLowerCase();const list=$('#actions-library');list.replaceChildren();
  const make=(name,icon,sub,key)=>{if(!(name+' '+sub).toLocaleLowerCase().includes(search))return null;
    const item=button('',()=>addAction(key),'action-preset');item.draggable=false;item.dataset.action=key;item.setAttribute('aria-label','Legg til '+name);
    item.append(text('span',icons[icon],'action-symbol'),element('span',{},text('span',name),text('small',sub)));
    item.addEventListener('dragstart',e=>{e.dataTransfer.setData('application/x-deck-action',key);e.dataTransfer.effectAllowed='copy';});return item;};
  if(('installerte programmer app launcher'.includes(search)||!search))list.append(button('▦ Installerte programmer',openProgramPicker,'program-launcher'));
  const groups=new Map();for(const [key,k] of Object.entries(kinds)){const sub=key==='page'?'Mapper og undersider':key==='hotkey'?'Ta opp en tastekombinasjon':key==='open'?'Velg direkte fra datamaskinen':key==='delay'?'Mellom trinn i en multihandling':'Tilpass etter behov';const item=make(k.name,k.icon,sub,key);if(item){if(!groups.has(k.group))groups.set(k.group,[]);groups.get(k.group).push(item);}}
  for(const [group,items] of groups){list.append(text('div',group.toUpperCase(),'library-group'),...items);}
  if(actionCatalog.packs.length){const packed=new Map();actionCatalog.packs.forEach((p,i)=>{const item=make(p.name,p.icon||'ok',p.actions.length>1?`${p.actions.length} handlinger`:'Ferdig handling','pack:'+i);if(item){if(!packed.has(p.group))packed.set(p.group,[]);packed.get(p.group).push(item);}});for(const [group,items] of packed)list.append(text('div',group.toUpperCase(),'library-group'),...items);}
  else {const ready=presets.map((p,i)=>make(p.name,p.icon,'Ferdig handling','preset:'+i)).filter(Boolean);if(ready.length)list.append(text('div','KLARE TIL BRUK','library-group'),...ready);}
  if(!list.children.length)list.append(element('div',{class:'library-empty'},text('strong','Ingen treff'),text('span','Prøv et annet søkeord.')));
}
function applyProgramDetails(result,index=0) {
  if(!result?.target)return;
  mutate(()=>{
    const base=current(),actions=activeActions();
    if(!base||!actions?.[index])return;
    Object.assign(actions[index],{type:'open',target:result.target,process:result.process||'',reuse:result.reuse!==false});
    const view=appearance(base);view.label=result.name||view.label;view.icon=result.icon||view.icon;
  });
  toast(`«${result.name}» bruker nå programikonet og fokuserer et åpent vindu.`);
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
  toast(`«${result.name}» er lagt på knapp ${id}.`);
}
function renderProgramResults() {
  const query=$('#program-search').value.trim().toLocaleLowerCase();
  const matches=installedPrograms.map((item,index)=>({...item,index})).filter(item=>!query||item.name.toLocaleLowerCase().includes(query));
  const list=$('#program-results');
  list.replaceChildren(...matches.map(item=>{
    const choice=button('',()=>installProgram(item.target).catch(showError),'program-choice',`Legg ${item.name} på valgt knapp`);
    choice.dataset.program=item.index;choice.dataset.label=item.name;choice.append(text('span',item.name.slice(0,1).toUpperCase(),'program-symbol'),
      element('span',{},text('strong',item.name),text('small','Dra til en knapp eller klikk for valgt plass')));
    return choice;
  }));
  if(!matches.length)list.append(element('div',{class:'program-empty'},text('strong','Ingen programmer funnet'),text('span','Prøv et kortere søkeord, eller bruk «Velg programfil».')));
  $('#program-count').textContent=`${matches.length} av ${installedPrograms.length} programmer`;
}
async function openProgramPicker() {
  const dialog=$('#program-dialog');dialogReturnFocus=document.activeElement;
  dialog.show();$('#program-results').replaceChildren(text('p','Leser Start-menyen …','hint program-loading'));
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
function editAction(index,key,value) {mutate(()=>activeActions()[index][key]=value,false);}
function renderInspector() {
  recording=null;const panel=$('#inspector'),base=current(),b=appearance();panel.replaceChildren();
  panel.append(element('div',{class:'inspector-title'},element('div',{},text('div',`KNAPP ${String(selected).padStart(2,'0')}`,'section-label'),text('h2',b?'Tilpass knappen':'En ledig plass'))));
  if(!b){panel.append(element('div',{class:'empty-inspector'},text('strong','Hva vil du ha her?'),text('p','Dra en handling hit fra listen til venstre. Eller velg en av snarveiene under.')));
    panel.append(button('▦ Velg installert program',openProgramPicker,'add-action'),button('＋ Legg til hurtigtast',()=>addAction('hotkey'),'add-action'),button('▱ Åpne fil eller program',()=>addAction('open'),'add-action'),button('▶ Spill / pause',()=>addAction('preset:3'),'add-action'));if(clipboard)panel.append(button('Lim inn kopiert knapp',pasteButton,'add-action'));return;}
  panel.append(field('Navn på knappen',b.label,value=>mutate(()=>appearance().label=value,false),{placeholder:'Et kort, tydelig navn'}));
  const appearanceRow=element('div',{class:'appearance-row'},text('span','Ikonfarge','hint'));
  const color=element('input',{type:'color',value:b.color||'#35D07F','aria-label':'Ikonfarge'});color.addEventListener('input',()=>{mutate(()=>appearance().color=color.value,false);panel.querySelector('.selected-icon-image')?.replaceWith(iconVisual(current().icon,color.value,'selected-icon-image'));});appearanceRow.append(color,text('span','Vises på panelet','hint'));panel.append(appearanceRow);
  const selectedIcon=packIcons.get(b.icon);
  panel.append(element('div',{class:'selected-pack-icon'},iconVisual(b.icon,b.color,'selected-icon-image'),element('div',{},text('strong',selectedIcon?.name||iconNames[b.icon]||'Standardikon'),button(iconPack?`Velg blant ${iconPack.count.toLocaleString('nb-NO')} ikoner …`:'Åpne stort ikonbibliotek …',openIcons,'text-button'))));
  const upload=element('input',{type:'file',accept:'image/png,image/jpeg,image/gif,image/webp',hidden:'hidden'});upload.onchange=()=>uploadImage(upload.files[0]).catch(showError);panel.append(upload,button('Bilde fra fil …',()=>upload.click(),'outline'));
  panel.append(element('div',{class:'title-controls'},field('Tekststørrelse',String(base.title?.size||16),v=>mutate(()=>{base.title??={};base.title.size=Number(v);}),{values:['16','20','24','28']}),field('Plassering',base.title?.position||'bottom',v=>mutate(()=>{base.title??={};base.title.position=v;}),{values:[['bottom','Nederst'],['top','Øverst'],['middle','Midten'],['hidden','Skjul tekst']]})));
  panel.append(element('div',{class:'option-buttons'},button(base.title?.bold?'Fet tekst ✓':'Fet tekst',()=>mutate(()=>{base.title??={};base.title.bold=!base.title.bold;}),'outline'),button(config.profiles[profile].pinned?.includes(base)?'◆ Løsne':'◇ Fest på alle sider',togglePin,'outline')));
  panel.append(field('Knappetype',base.states?'Veksleknapp':'Vanlig knapp',value=>mutate(()=>{if(value==='Veksleknapp'){base.states=[{label:base.label,icon:base.icon,color:base.color,actions:clone(base.actions||[])},{label:base.label+' · på',icon:base.icon,color:'#FFA868',actions:clone(base.actions||[])}];}else{base.actions=clone(base.states?.[0].actions||base.actions);delete base.states;}editState=0;}),{values:['Vanlig knapp','Veksleknapp']}));
  if(base.states){panel.append(field('Rediger tilstand',String(editState+1),value=>{editState=Number(value)-1;renderGrid();renderInspector();},{values:base.states.map((_,i)=>String(i+1))}),text('p','Trykk kjører denne tilstanden og viser deretter den neste. Dette er lokal knappetilstand, ikke bekreftet appstatus.','hint'));}
  const choices=element('div',{class:'icon-grid',role:'group','aria-label':'Velg ikon'});
  for(const [key,glyph] of Object.entries(icons)) {const item=button(glyph,()=>mutate(()=>appearance().icon=key),'icon-choice'+((b.icon||'ok')===key?' active':''),iconNames[key]);item.setAttribute('aria-label',iconNames[key]);item.setAttribute('aria-pressed',(b.icon||'ok')===key);choices.append(item);}
  panel.append(element('details',{class:'quick-icons'},text('summary','Hurtigikoner'),choices));
  panel.append(text('div',(activeActions()?.length>1?'MULTIHANDLING · ':'HANDLINGER · ')+(activeActions()?.length||0)+' TRINN','section-label'));
  (activeActions()||[]).forEach((action,index)=>panel.append(renderStep(action,index,activeActions().length)));
  const addSelect=element('select',{'aria-label':'Legg til et nytt handlingstrinn'});addSelect.append(element('option',{value:'',text:'＋ Legg til handling …'}));for(const [key,k] of Object.entries(kinds))addSelect.append(element('option',{value:key,text:k.name}));addSelect.addEventListener('change',()=>{if(addSelect.value)addAction(addSelect.value);});panel.append(addSelect);
  panel.append(element('div',{class:'inspector-tools'},button('Kopier',copyButton,'outline'),button('Lim inn',pasteButton,'outline'),button('Tøm knapp',clearButton,'quiet danger')));
  panel.append(field('Flytt til spor',String(selected),value=>moveSlot(selected,Number(value)),{values:Array.from({length:18},(_,i)=>String(i+1))}));
  panel.append(text('p','Endringer lagres automatisk. Knappens handling kjøres bare når du trykker på panelet.','hint'));
}
function renderStep(action,index,count) {
  const k=kinds[action.type]||kinds.hotkey;
  const step=element('section',{class:'step','aria-label':`Trinn ${index+1}: ${k.name}`,draggable:'false','data-step':index});
  step.addEventListener('dragstart',event=>{if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return event.preventDefault();event.dataTransfer.setData('application/x-deck-step',String(index));event.stopPropagation();});
  step.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer.types).includes('application/x-deck-step'))event.preventDefault();});
  step.addEventListener('drop',event=>{const value=event.dataTransfer.getData('application/x-deck-step');if(value==='')return;event.preventDefault();const source=Number(value);mutate(()=>{const actions=activeActions();actions.splice(index,0,actions.splice(source,1)[0]);});});
  const move=delta=>{if(index+delta<0||index+delta>=count)return;mutate(()=>{const a=activeActions();[a[index],a[index+delta]]=[a[index+delta],a[index]];});};
  const up=button('↑',()=>move(-1),'quiet','Flytt trinn opp'),down=button('↓',()=>move(1),'quiet','Flytt trinn ned');up.disabled=index===0;down.disabled=index===count-1;
  step.append(element('div',{class:'step-header'},text('strong',`${index+1}. ${k.name}`),up,down,button('×',()=>mutate(()=>activeActions().splice(index,1)),'quiet danger','Fjern trinn')));
  let values=['page','folder'].includes(action.type)?Object.keys(config.profiles[profile].pages):action.type==='profile'?Object.keys(config.profiles):null;
  if(action.type==='back'){step.append(text('p','Går tilbake ett nivå i mappestakken.','hint'));return step;}
  if(action.type==='home'){step.append(text('p','Åpner standardprofilens første side og holder den valgt til du bytter aktivt program.','hint'));return step;}
  const parameter=field(k.label,action[k.field],value=>editAction(index,k.field,value),{type:['delay','press'].includes(action.type)?'number':'text',placeholder:k.placeholder,values,multiline:['text','shell'].includes(action.type)});
  if(action.type==='open') {
    const input=parameter.querySelector('input');input.setAttribute('data-path',index);parameter.append(button('Velg program …',async()=>{try{const result=await api('command/pick',{kind:'program'});if(result.target){applyProgramDetails(result,index);}}catch(error){showError(error);}},'text-button'));
  }
  step.append(parameter);
  if(action.type==='open') {
    const focus=element('label',{class:'check-option'},element('input',{type:'checkbox'}),element('span',{},text('strong','Fokuser åpent vindu'),text('small','Starter programmet bare når det ikke allerede kjører.')));
    const checkbox=focus.querySelector('input');checkbox.checked=!!action.reuse;checkbox.onchange=()=>mutate(()=>activeActions()[index].reuse=checkbox.checked);step.append(focus);
    if(action.reuse)step.append(field('Prosessnavn',action.process||'',value=>editAction(index,'process',value),{placeholder:'for eksempel chrome.exe'}));
  }
  if(action.type==='hotkey') {const record=button('⌨ Ta opp hurtigtast',()=>{recording={index,input:parameter.querySelector('input'),button:record};record.textContent='Trykk kombinasjonen · Esc avbryter';record.classList.add('recording');record.focus();},'outline record');step.append(record);}
  if(['page','folder'].includes(action.type))step.append(button('＋ Lag ny underside',()=>newPage(true,index),'text-button'));
  if(action.type==='http'){step.append(field('Metode',action.method||'GET',v=>editAction(index,'method',v),{values:['GET','POST','PUT','PATCH','DELETE']}),field('Innhold (valgfritt)',action.body||'',v=>editAction(index,'body',v),{multiline:true}));}
  if(action.type==='set')step.append(field('Verdi',action.value||'',v=>editAction(index,'value',v)));
  return step;
}
function copyButton() {if(!current())return;clipboard=clone(current());toast('Knappen er kopiert. Velg et spor og trykk Ctrl+V.');}
function pasteButton() {if(!clipboard)return toast('Kopier en knapp først.');mutate(()=>{const list=owner(),at=list.findIndex(b=>b.id===selected);if(at>=0)list.splice(at,1);list.push({...clone(clipboard),id:selected});});}
function dialog(title,fields,onSave,saveLabel='Lagre') {
  const d=$('#form-dialog');dialogReturnFocus=document.activeElement;$('#dialog-title').textContent=title;$('#dialog-error').textContent='';$('#dialog-submit').textContent=saveLabel;
  $('#dialog-fields').replaceChildren(...fields.map(f=>{const label=element('label',{class:'form-field'},text('span',f.label));const input=f.options?element('select',{name:f.name}):element(f.multiline?'textarea':'input',{name:f.name,type:f.type||'text',required:f.required?'required':undefined});if(f.options)options(input,f.options,f.value||f.options[0][0]);else if(f.type==='checkbox')input.checked=!!f.value;else input.value=f.value||'';label.append(input);if(f.note)label.append(text('small',f.note,'hint'));return label;}));
  d.querySelector('form').onsubmit=event=>{if(event.submitter?.value==='cancel')return;event.preventDefault();const form=new FormData(event.target);const values={};for(const f of fields)values[f.name]=f.type==='checkbox'?form.has(f.name):form.get(f.name);try{onSave(values);d.close();}catch(error){$('#dialog-error').textContent=error.message;}};
  d.showModal();setTimeout(()=>d.querySelector('input,textarea')?.focus(),30);
}
function openTemplates() {
  if(!actionCatalog.templates.length)return toast('Ingen ferdige oppsett er tilgjengelige.');
  const choices=actionCatalog.templates.map((template,index)=>[String(index),`${template.name} · ${template.description}`]);
  dialog('Ferdige profiloppsett',[{name:'template',label:'Velg oppsett',options:choices,value:'0',note:'Oppsettet legges til som en ny profil. Dine eksisterende profiler beholdes.'}],values=>{
    const template=actionCatalog.templates[Number(values.template)];if(!template)throw new Error('Velg et gyldig oppsett.');
    let name=template.name,suffix=2;while(config.profiles[name])name=`${template.name} ${suffix++}`;
    mutate(()=>{config.profiles[name]=clone(template.profile);profile=name;page=Object.keys(config.profiles[name].pages)[0];selected=1;editState=0;});renderAll();toast(`Profilen «${name}» er lagt til.`);
  },'Legg til profil');
}
function newPage(link=false,index=0) {dialog(link?'Lag en underside':'Ny side',[{name:'name',label:'Navn på siden',required:true}],values=>{
  const name=values.name.trim();if(!name||config.profiles[profile].pages[name])throw new Error('Velg et nytt sidenavn.');
  mutate(()=>{config.profiles[profile].pages[name]=[];if(link){activeActions()[index].page=name;activeActions()[index].type='folder';
    config.profiles[profile].pages[name].push({id:1,label:'Tilbake',icon:'home',color:'#A3B2BC',actions:[{type:'back'}]});}else page=name;});renderPages();
});}
function renameProfile(old,name) {
  if(name===old)return;
  if(!name||config.profiles[name])throw new Error('Velg et nytt profilnavn.');
  const entries=Object.entries(config.profiles);config.profiles=Object.fromEntries(entries.map(([key,value])=>[key===old?name:key,value]));
  if(config.default_profile===old)config.default_profile=name;
  for(const item of Object.values(config.profiles))rewriteActions(profileButtons(item),a=>a.type==='profile'&&a.profile===old?{...a,profile:name}:a);
  for(const t of config.triggers||[])for(const a of t.actions||[])if(a.type==='profile'&&a.profile===old)a.profile=name;
}
async function profileSettings() {
  let running=[];try{running=(await api('processes')).names||[];}catch(error){}
  const processChoices=[['','— Velg et kjørende program —'],...running.map(name=>[name,name])];
  dialog('Profilinnstillinger',[
  {name:'name',label:'Profilnavn',value:profile,required:true},
  {name:'program',label:'Legg til et kjørende program',options:processChoices,value:'',note:'Velg programmet som skal aktivere profilen.'},
  {name:'match',label:'Regler for automatisk profilbytte',value:(config.profiles[profile].match||[]).join(', '),note:'Flere regler skilles med komma. Bruk process:claude.exe for en terminalprosess eller title:codex for vindustittel.'},
  {name:'default',label:'Bruk som standardprofil',type:'checkbox',value:profile===config.default_profile},
  {name:'remove',label:'Slett profilen og fjern handlinger som peker hit',type:'checkbox'}],values=>{
    if(values.remove){
      if(Object.keys(config.profiles).length===1)throw new Error('Behold minst én profil.');
      if(!confirm(`Slette profilen «${profile}» og handlinger som peker hit?`))return;
      mutate(()=>{const old=profile;delete config.profiles[old];profile=Object.keys(config.profiles)[0];page=Object.keys(config.profiles[profile].pages)[0];if(config.default_profile===old)config.default_profile=profile;
        for(const item of Object.values(config.profiles))rewriteActions(profileButtons(item),a=>a.type==='profile'&&a.profile===old?null:a);
        for(const t of config.triggers||[])t.actions=(t.actions||[]).filter(a=>!(a.type==='profile'&&a.profile===old));});renderAll();return;
    }
    const name=values.name.trim();if(!name||(name!==profile&&config.profiles[name]))throw new Error('Profilnavnet er allerede i bruk.');
    mutate(()=>{renameProfile(profile,name);profile=name;const rules=values.match.split(',').map(s=>s.trim()).filter(Boolean);if(values.program&&!rules.includes(values.program))rules.push(values.program);config.profiles[profile].match=rules;if(values.default)config.default_profile=profile;});renderAll();
  });
}
function appSettings() {dialog('Programinnstillinger',[
  {name:'autostart',label:'Start USB-verten automatisk når jeg logger inn',type:'checkbox',value:!!dashboard.autostart,note:'Panelet blir klart uten at editorvinduet åpnes. Du kan fortsatt åpne Agent Deck fra skrivebordet for å redigere.'},
  {name:'autoProfiles',label:'Bytt profil automatisk etter aktivt program',type:'checkbox',value:config.auto_profiles!==false,note:'Slå av hvis panelet alltid skal bli på programstarteren til du bytter profil selv.'}
],values=>{mutate(()=>config.auto_profiles=values.autoProfiles);command('autostart',{enabled:values.autostart}).catch(showError);},'Bruk');}
function pageSettings() {dialog('Sideinnstillinger',[{name:'name',label:'Sidenavn',value:page,required:true},{name:'remove',label:'Slett denne siden og fjern handlinger som peker hit',type:'checkbox'}],values=>{
  const pages=config.profiles[profile].pages,name=values.name.trim(),old=page;
  if(values.remove&&Object.keys(pages).length===1)throw new Error('Behold minst én side.');
  if(!values.remove&&(!name||(name!==old&&pages[name])))throw new Error('Velg et nytt sidenavn.');
  if(values.remove&&!confirm(`Slette «${old}» og fjerne handlinger i denne profilen som peker til siden?`))return;
  mutate(()=>{
    if(values.remove){delete pages[old];page=Object.keys(pages)[0];}
    else {config.profiles[profile].pages=Object.fromEntries(Object.entries(pages).map(([key,value])=>[key===old?name:key,value]));page=name;}
    const update=a=>['page','folder'].includes(a.type)&&a.page===old?(values.remove?null:{...a,page:name}):a;
    rewriteActions(profileButtons(config.profiles[profile]),update);
    if(config.default_profile===profile)for(const t of config.triggers||[])t.actions=(t.actions||[]).flatMap(a=>{const changed=update(a);return changed?[changed]:[];});
  });renderAll();
});}
async function exportConfig() {await save();const bundle=await api('export');const blob=new Blob([JSON.stringify(bundle,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=element('a',{href:url,download:'agent-deck-profiler.json'});a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function importConfig(file) {
  if(!file)return;if(file.size>16*1024*1024)throw new Error('Oppsettet er for stort.');const data=JSON.parse(await file.text());
  if(!data.profiles||!Object.keys(data.profiles).length)throw new Error('Filen inneholder ingen profiler.');
  const names=Object.keys(data.profiles);if(!confirm(`Erstatt oppsettet med ${names.length} profiler fra «${file.name}»? ${(data.triggers||[]).length} automatiske regler følger med. Du kan angre.`))return;
  if(data.assets){const replacements={};for(const [id,image] of Object.entries(data.assets)){const result=await api('image',{data:image});replacements[id]=result.id;}const visit=value=>{if(Array.isArray(value))value.forEach(visit);else if(value&&typeof value==='object')for(const [key,item] of Object.entries(value)){if(key==='icon'&&replacements[item])value[key]=replacements[item];else visit(item);}};delete data.assets;visit(data);}
  const previous=clone(config);remember();config=data;
  try {ensureSelection();const error=draftError();if(error)throw new Error(error);version++;dirty=true;await save();renderAll();toast('Oppsettet er importert.');}
  catch(error){config=previous;history.pop();renderAll();throw error;}
}
async function command(name,data={}) {const result=await api('command/'+name,data);if(result.message)toast(result.message);await pollStatus();}
function renderStatus() {
  const connected=dashboard.device?.connected;
  $('#led').classList.toggle('connected',!!connected);$('#led').classList.toggle('waiting',dashboard.running&&!connected);
  const context=[dashboard.device?.profile,dashboard.device?.page].filter(Boolean).join(' / ');
  const automatic=dashboard.device?.auto_profile?`Auto: ${dashboard.device.auto_profile}`:null;
  $('#connection').textContent=connected?[dashboard.device.port,context,automatic,dashboard.device.buttons?dashboard.device.buttons+' knapper':null].filter(Boolean).join(' · '):dashboard.running?(dashboard.connection||'Venter på enheten'):'Verten er stoppet';
  $('#connection').title=dashboard.device?.error||'';
  const agentNames={codex:'Codex',claude:'Claude',zcode:'ZCode'};
  $('#agent-status').replaceChildren(...Object.entries(agentNames).map(([key,name])=>text('span',`${name} ${dashboard.agents?.[key]?'kjører':'klar'}`,'agent-pill'+(dashboard.agents?.[key]?' running':''))));
  $('#host-toggle').textContent=dashboard.running?'Stopp vert':'Start vert';
  const same=connected&&dashboard.device?.profile===profile&&dashboard.device?.page===page;
  $('#activate').textContent=same?'✓ Vises på enheten':'Vis på enheten';$('#activate').classList.toggle('is-live',!!same);
  const last=dashboard.device?.last_action,recent=last&&Date.now()/1000-last.at<15;
  $('#device-summary').textContent=recent?`Sist trykket: ${last.ok?'✓':'✕'} ${last.label}${last.error?' · '+last.error:''}`:connected?(same?'Denne profilen og siden er aktiv på panelet.':`Panelet viser nå ${dashboard.device.profile} / ${dashboard.device.page}.`):dashboard.running?'Panelet er ikke tilkoblet.':'USB-verten er stoppet.';
  if(last?.at>lastActionAt){if(lastActionAt)toast(`${last.ok?'✓':'✕'} ${last.label}${last.error?' · '+last.error:''}`);lastActionAt=last.at;}
  document.title=connected&&context?`Agent Deck · ${context}`:'Agent Deck';
}
async function pollStatus() {try{dashboard=await api('status');renderStatus();}catch(error){$('#connection').textContent='Editoren er frakoblet';$('#led').classList.remove('connected');}}
document.addEventListener('keydown',event=>{
  if(recording){event.preventDefault();event.stopPropagation();if(event.key==='Escape'){recording.button.textContent='⌨ Ta opp hurtigtast';recording.button.classList.remove('recording');recording=null;return;}
    if(['Control','Shift','Alt','Meta'].includes(event.key))return;
    const aliases={' ':'space',Escape:'esc',ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Delete:'delete',PageUp:'pageup',PageDown:'pagedown','/':'slash','`':'grave'};
    const parts=[event.ctrlKey?'ctrl':null,event.altKey?'alt':null,event.shiftKey?'shift':null,event.metaKey?'win':null,aliases[event.key]||event.key.toLowerCase()].filter(Boolean);
    const value=parts.join('+'),index=recording.index;recording=null;editAction(index,'keys',value);renderInspector();return;
  }
  const menu=$('#key-menu');
  if(!menu.hidden){const items=[...menu.querySelectorAll('[role="menuitem"]')],at=items.indexOf(document.activeElement);
    if(event.key==='Escape'){event.preventDefault();hideKeyMenu(true);return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?items.length-1:(at+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next].focus();return;}}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||$('#form-dialog').open||$('#icon-dialog').open)return;
  if((event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')&&current()){event.preventDefault();openKeyMenu(selected);return;}
  if(event.ctrlKey||event.metaKey) {const key=event.key.toLowerCase();if(['z','y','c','v','d'].includes(key)){event.preventDefault();if(key==='z')undo(event.shiftKey);if(key==='y')undo(true);if(key==='c')copyButton();if(key==='v')pasteButton();if(key==='d')duplicateButton();}}
});
function hideKeyMenu(restore=false) {$('#key-menu').hidden=true;if(restore)keyMenuReturnFocus?.focus();keyMenuReturnFocus=null;}
function openKeyMenu(id,x,y) {
  let tile=$(`[data-slot="${id}"]`);if(!tile||!visibleButtons().some(b=>b.id===id))return;
  selected=id;editState=0;renderGrid();renderInspector();tile=$(`[data-slot="${id}"]`);keyMenuReturnFocus=tile;
  const menu=$('#key-menu'),pinned=config.profiles[profile].pinned?.some(b=>b.id===id);
  menu.querySelector('[data-menu="pin"]').textContent=pinned?'Løsne fra alle sider':'Fest på alle sider';menu.hidden=false;
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
  if(!drag.active){drag.active=true;drag.ghost=text('div',drag.source.dataset.slot?'Flytt knapp '+drag.source.dataset.slot:drag.source.dataset.label||drag.source.innerText.split('\n')[0],'drag-ghost');document.body.append(drag.ghost);document.body.classList.add('dragging');if(drag.source.dataset.program!==undefined)$('#program-dialog').classList.add('drag-through');}
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
  if(token){const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Deck-Token':token},body:'{}'});if(!response.ok)throw new Error('Åpne programmet med Agent-Deck.cmd.');window.history.replaceState(null,'',location.pathname);}
  const state=await api('config');config=state.config;revision=state.revision;profile=config.default_profile||Object.keys(config.profiles)[0];page=Object.keys(config.profiles[profile].pages)[0];
  try{const [,catalog]=await Promise.all([loadIconPack(),api('action-packs')]);actionCatalog=catalog;}catch(error){toast('Tilleggspakkene kunne ikke lastes. '+error.message);}
  renderAll();renderLibrary();setSaveState('✓ Oppsettet er klart');await pollStatus();
  $('#profile').onchange=()=>{profile=$('#profile').value;page=Object.keys(config.profiles[profile].pages)[0];selected=1;editState=0;renderAll();};
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
  $('#key-menu').onclick=event=>{const action=event.target.closest('[data-menu]')?.dataset.menu;if(!action)return;hideKeyMenu();if(action==='duplicate')duplicateButton();if(action==='copy')copyButton();if(action==='pin')togglePin();if(action==='clear')clearButton();};
  $('#profile-templates').onclick=openTemplates;
  $('#new-profile').onclick=()=>dialog('Ny profil',[{name:'name',label:'Profilnavn',required:true}],values=>{const name=values.name.trim();if(!name||config.profiles[name])throw new Error('Velg et nytt profilnavn.');mutate(()=>{config.profiles[name]={match:[],pages:{Hoved:[]}};profile=name;page='Hoved';});renderAll();});
  $('#export').onclick=()=>exportConfig().catch(showError);$('#import').onclick=()=>$('#import-file').click();$('#import-file').onchange=async()=>{try{await importConfig($('#import-file').files[0]);}catch(error){showError(error);}$('#import-file').value='';};
  $('#activate').onclick=async()=>{try{await save();if(!dashboard.running)await api('command/start',{});await command('activate',{profile,page});}catch(error){showError(error);}};
  $('#host-toggle').onclick=async()=>{const b=$('#host-toggle');b.disabled=true;try{await command(dashboard.running?'stop':'start');}catch(error){showError(error);}finally{b.disabled=false;}};
  $('#terminal').onclick=()=>command('terminal').catch(showError);
  $('#reload').onclick=async()=>{if(dirty&&!confirm('Forkaste ulagrede endringer og lese oppsettet fra disken?'))return;try{const state=await api('config');config=state.config;revision=state.revision;dirty=false;conflicted=false;history=[];future=[];$('#reload').hidden=true;renderAll();setSaveState('✓ Oppsettet er lastet inn på nytt');}catch(error){showError(error);}};
  setInterval(pollStatus,3000);
}
start().catch(error=>{setSaveState('Editoren kunne ikke starte',error.message);toast(error.message);});
