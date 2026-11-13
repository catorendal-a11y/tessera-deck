'use strict';
// Editor part 2 of 3: the action list, the inspector, drawing the keys, menus and dragging.
/* Action categories fold like Stream Deck's action list. The folded set is remembered; a search opens everything. */
const foldedCategories=(()=>{try{return new Set(JSON.parse(localStorage.getItem('tessera-folded')||'[]'));}catch{return new Set();}})();
const foldPrefStored=(()=>{try{return localStorage.getItem('tessera-folded')!==null;}catch{return false;}})();
let categoryOrder=0;
function category(name,items,tone,searching) {
  if(!foldPrefStored&&!searching&&categoryOrder++>0)foldedCategories.add(name);
  const box=element('details',{class:'lib-cat tone-'+tone,'data-category':name});box.open=searching||!foldedCategories.has(name);
  box.append(element('summary',{},text('span',name),text('small',String(items.length))),element('div',{class:'lib-items'},...items));
  box.addEventListener('toggle',()=>{if(searching)return;box.open?foldedCategories.delete(name):foldedCategories.add(name);
    try{localStorage.setItem('tessera-folded',JSON.stringify([...foldedCategories]));}catch{}});
  return box;
}
/* The action list is four tabs, so a tab holds a handful of groups instead of eighteen. A search looks in all of them. */
const LIBRARY_TABS=[['basics','Basics'],['widgets','Widgets'],['ready','Ready-made'],['apps','Apps']];
const GENERAL_GROUPS=new Set(['Windows','Browser','Meetings','Media','Editing','Productivity','Window management','Ready to use']);
let libraryTab=(()=>{try{const stored=localStorage.getItem('tessera-library-tab');return LIBRARY_TABS.some(tab=>tab[0]===stored)?stored:'basics';}catch{return 'basics';}})();
function renderLibrary() {
  const search=$('#action-search').value.toLocaleLowerCase();const list=$('#actions-library');list.replaceChildren();categoryOrder=0;
  const make=(name,icon,sub,key)=>{if(!(name+' '+sub).toLocaleLowerCase().includes(search))return null;
    const item=button('',()=>addAction(key),'action-preset');item.draggable=false;item.dataset.action=key;item.title=name;item.setAttribute('aria-label','Add '+name);
    item.append(actionSymbol(icon),element('span',{},text('span',name),text('small',sub)));
    item.addEventListener('dragstart',e=>{e.dataTransfer.setData('application/x-deck-action',key);e.dataTransfer.effectAllowed='copy';});return item;};
  const searching=!!search,put=(tab,node)=>{if(searching||tab===libraryTab)list.append(node);};
  $('#library-tabs').replaceChildren(...LIBRARY_TABS.map(([id,name])=>{
    const on=!searching&&libraryTab===id,tab=button(name,()=>{libraryTab=id;try{localStorage.setItem('tessera-library-tab',id);}catch{}$('#action-search').value='';renderLibrary();},'library-tab'+(on?' on':''));
    tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(on));return tab;}));
  if(('installed programs app launcher'.includes(search)||!search))put('apps',button('Installed programs …',openProgramPicker,'program-launcher'));
  const ready=WIDGETS.map(w=>{const item=make(w.name,'widget',w.sub,'widget:'+w.kind);if(item)item.querySelector('.action-symbol').innerHTML=`<svg viewBox="0 0 24 24">${w.path}</svg>`;return item;}).filter(Boolean);
  if(ready.length){if(searching)list.append(category('Widgets',ready,0,true));else if(libraryTab==='widgets')list.append(text('p','A widget is a wide key that shows something live. Drag one to a key with a free slot to its right.','hint library-note'),element('div',{class:'lib-items lib-flat'},...ready));}
  const groups=new Map();for(const [key,k] of Object.entries(kinds)){const sub=key==='page'?'Folders and subpages':key==='hotkey'?'Record a key combination':key==='open'?'Choose directly from the computer':key==='delay'?'Between steps in a multi-action':'Customize as needed';const item=make(k.name,k.icon,sub,key);if(item){if(!groups.has(k.group))groups.set(k.group,[]);groups.get(k.group).push(item);}}
  [...groups].forEach(([group,items],index)=>put('basics',category(group,items,index%4,searching)));
  if(actionCatalog.packs.length){const packed=new Map();actionCatalog.packs.forEach((p,i)=>{const item=make(p.name,p.icon||'ok',p.actions.length>1?`${p.actions.length} actions`:'Ready-made action','pack:'+i);if(item){if(!packed.has(p.group))packed.set(p.group,[]);packed.get(p.group).push(item);}});let tone=groups.size;for(const [group,items] of packed)put(GENERAL_GROUPS.has(group)?'ready':'apps',category(group,items,tone++%4,searching));}
  else {const ready=presets.map((p,i)=>make(p.name,p.icon,'Ready-made action','preset:'+i)).filter(Boolean);if(ready.length)put('ready',category('Ready to use',ready,0,searching));}
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
  toast(`“${result.name}” was placed on key ${id}.`);
}
function renderProgramResults() {
  const query=$('#program-search').value.trim().toLocaleLowerCase();
  const matches=installedPrograms.map((item,index)=>({...item,index})).filter(item=>!query||item.name.toLocaleLowerCase().includes(query));
  const list=$('#program-results');
  list.replaceChildren(...matches.map(item=>{
    const choice=button('',()=>installProgram(item.target).catch(showError),'program-choice',`Put ${item.name} on the selected key`);
    choice.dataset.program=item.index;choice.dataset.label=item.name;choice.append(text('span',item.name.slice(0,1).toUpperCase(),'program-symbol'),
      element('span',{},text('strong',item.name),text('small','Drag to a key or click for the selected slot')));
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
/* Groups a run of inspector rows under a collapsible heading. Wrapped last-first so the earlier indexes stay valid. */
let inspectorTab='look';  // which group of key settings shows: look, actions or more
function wrapSection(panel,from,to,title,open,cls='') {
  const nodes=[...panel.children].slice(from,to);if(!nodes.length)return;
  const section=element('details',{class:'inspector-section '+cls});section.open=open;
  panel.insertBefore(section,nodes[0]);section.append(text('summary',title),element('div',{class:'section-body'},...nodes));
}
function renderInspector() {
  const controls='input,select,textarea,button,summary';
  recording=null;const panel=$('#inspector'),base=current(),b=appearance(),focusAt=[...panel.querySelectorAll(controls)].indexOf(document.activeElement);panel.replaceChildren();
  panel.append(element('div',{class:'inspector-title'},element('div',{},text('div',`KEY ${String(selected).padStart(2,'0')}`,'section-label'),b?null:text('h2','An empty slot'))));
  const firstField=panel.children.length;
  if(!b){panel.append(element('div',{class:'empty-inspector'},text('strong','What do you want here?'),text('p','Drag an action here from the action list. Or pick one of the shortcuts below.')));
    panel.append(button('▦ Choose installed program',openProgramPicker,'add-action'),button('＋ Add hotkey',()=>addAction('hotkey'),'add-action'),button('▱ Open file or program',()=>addAction('open'),'add-action'),button('▶ Play / pause',()=>addAction('preset:3'),'add-action'));if(clipboard)panel.append(button('Paste copied key',pasteButton,'add-action'));return;}
  const previewLabel=text('span',resolveLabel(b.label)||' ','prop-label');
  const meter=text('small','','label-meter');
  const updateMeter=()=>{const full=expandLabel(appearance()?.label),bytes=new TextEncoder().encode(full).length,variable=/[$][(]/.test(appearance()?.label||'');
    meter.classList.toggle('over',bytes>LABEL_BYTES);
    meter.textContent=bytes>LABEL_BYTES?`Too long for the panel: it shows “${panelLabel(full)}”`:`${bytes} / ${LABEL_BYTES} bytes on the panel${variable?' with the current values':''}`;};
  const nameInput=element('input',{type:'text',placeholder:'A short, clear name','aria-label':'Key name'});nameInput.value=b.label??'';
  nameInput.addEventListener('input',()=>{mutate(()=>appearance().label=nameInput.value,false,editKey('label'));updateMeter();previewLabel.textContent=resolveLabel(nameInput.value)||' ';});
  updateMeter();
  const color=element('input',{type:'color',value:b.color||'#35D07F','aria-label':'Icon color',title:'Icon color'});
  color.addEventListener('input',()=>{mutate(()=>appearance().color=color.value,false,editKey('color'));panel.querySelector('.prop-icon')?.replaceWith(iconVisual(current().icon,color.value,'prop-icon'));});
  const selectedIcon=packIcons.get(b.icon);
  const iconButton=button(`${selectedIcon?.name||iconNames[b.icon]||'Default icon'} · Choose …`,openIcons,'prop-field');
  const upload=element('input',{type:'file',accept:'image/png,image/jpeg,image/gif,image/webp',hidden:'hidden'});upload.onchange=()=>chooseImage(upload.files[0]).catch(showError);
  const sizeField=field('Text size',String(base.title?.size||16),v=>mutate(()=>{base.title??={};base.title.size=Number(v);}),{values:['16','20','24','28']});
  const positionField=field('Position',base.title?.position||'bottom',v=>mutate(()=>{base.title??={};base.title.position=v;}),{values:[['bottom','Bottom'],['top','Top'],['middle','Middle'],['hidden','Hide text']]});
  const boldButton=button(base.title?.bold?'Bold ✓':'Bold',()=>mutate(()=>{base.title??={};base.title.bold=!base.title.bold;}),'outline');
  const pinButton=button(config.profiles[profile].pinned?.includes(base)?'◆ Unpin':'◇ Pin',togglePin,'outline');
  const first=activeActions()?.[0];
  const actionButton=button(first?stepSummary(activeActions()):'No action yet · Add one below',
    ()=>{const target=panel.querySelector('.handling');if(target){target.open=true;target.scrollIntoView({block:'nearest',behavior:'smooth'});}},'prop-field');
  const row=(name,...nodes)=>element('div',{class:'prop-row'},text('span',name,'prop-name'),element('div',{class:'prop-value'},...nodes));
  const titleRow=row('Title',nameInput,meter);titleRow.classList.add('prop-row-title');
  const textRow=row('Text',sizeField,positionField,boldButton,pinButton);textRow.classList.add('prop-row-text');
  const head=element('div',{class:'prop-head'},text('b',first?(kinds[first.type]||kinds.hotkey).name:'No action yet'),button('Clear',clearButton,'prop-clear','Clear this key'));
  panel.append(element('div',{class:'prop-card'},head,element('div',{class:'prop-preview'},iconVisual(b.icon,b.color,'prop-icon'),previewLabel),
    element('div',{class:'prop-rows'},titleRow,row('Icon',color,iconButton,button('Image …',()=>upload.click(),'outline'),upload),
      textRow,...(wideRows(base,row)))));
  renderStyle(panel);
  const choices=element('div',{class:'icon-grid',role:'group','aria-label':'Choose icon'});
  for(const [key,glyph] of Object.entries(icons)) {const item=button(glyph,()=>mutate(()=>appearance().icon=key),'icon-choice'+((b.icon||'ok')===key?' active':''),iconNames[key]);item.setAttribute('aria-label',iconNames[key]);item.setAttribute('aria-pressed',(b.icon||'ok')===key);choices.append(item);}
  panel.append(element('details',{class:'quick-icons'},text('summary','Quick icons'),choices));
  const typeStart=panel.children.length;
  panel.append(field('Key type',base.states?'Toggle key':'Normal key',value=>mutate(()=>{if(value==='Toggle key'){base.states=[{label:base.label,icon:base.icon,color:base.color,actions:clone(base.actions||[])},{label:base.label+' · on',icon:base.icon,color:'#FFA868',actions:clone(base.actions||[])}];base.actions=[];}else if(base.states){const first=base.states[0];for(const key of ['label','icon','color'])if(first[key]!==undefined)base[key]=first[key];base.actions=clone(first.actions||[]);delete base.states;}editState=0;}),{values:['Normal key','Toggle key']}));
  if(base.states){panel.append(field('Edit state',String(editState+1),value=>{editState=Number(value)-1;renderGrid();renderInspector();},{values:base.states.map((_,i)=>String(i+1))}),text('p','A press runs this state and then shows the next one. This is local key state, not confirmed app status.','hint'));}
  const bindStart=panel.children.length;
  renderGauge(panel,base);
  renderBind(panel,base);
  const actionsStart=panel.children.length;
  panel.append(renderTriggers(base));
  panel.append(text('div',(activeActions()?.length>1?'MULTI-ACTION · ':'ACTIONS · ')+(activeActions()?.length||0)+(activeActions()?.length===1?' STEP':' STEPS'),'section-label'));
  (activeActions()||[]).forEach((action,index)=>panel.append(renderStep(action,index,activeActions().length)));
  const addSelect=element('select',{'aria-label':'Add a new action step'});addSelect.append(element('option',{value:'',text:'＋ Add action …'}));for(const [key,k] of Object.entries(kinds))addSelect.append(element('option',{value:key,text:k.name}));addSelect.addEventListener('change',()=>{if(addSelect.value)addAction(addSelect.value);});panel.append(addSelect);
  panel.append(element('div',{class:'inspector-tools'},button('Test',()=>testButton().catch(showError),'outline'),button('Copy',copyButton,'outline'),button('Paste',pasteButton,'outline'),button('Clear key',clearButton,'quiet danger')));
  panel.append(field('Move to slot',String(selected),value=>moveSlot(selected,Number(value)),{values:Array.from({length:18},(_,i)=>String(i+1))}));
  panel.append(text('p','Changes are saved automatically. The key action runs only when you press the panel.','hint'));
  wrapSection(panel,actionsStart,panel.children.length,'Actions',false,'handling');
  wrapSection(panel,bindStart,actionsStart,'Gauge and binding',false,'extras');
  wrapSection(panel,typeStart,bindStart,'Key type',false,'kind');
  // Tabs: one group of settings at a time instead of a stack of folded sections.
  const steps=activeActions()?.length||0,others=otherTriggerRows(base,row);
  const groups={look:[panel.querySelector('.prop-card'),...panel.querySelectorAll(':scope>.quick-icons')],actions:[...panel.querySelectorAll(':scope>.kind,:scope>.handling')],more:[...panel.querySelectorAll(':scope>.extras')]};
  if(others.length)panel.querySelector('.handling .section-body')?.prepend(element('div',{class:'other-triggers'},...others));
  const tabs=element('div',{class:'inspector-tabs',role:'tablist','aria-label':'Key settings'},...[['look','Look'],['actions',steps?`Actions · ${steps}`:'Actions'],['more','Gauge']].map(([id,name])=>{
    const tab=button(name,()=>{inspectorTab=id;renderInspector();},'inspector-tab'+(inspectorTab===id?' on':''));tab.setAttribute('role','tab');tab.setAttribute('aria-selected',String(inspectorTab===id));return tab;}));
  panel.insertBefore(tabs,panel.children[firstField]);
  for(const [id,nodes] of Object.entries(groups))for(const node of nodes){if(!node)continue;node.hidden=id!==inspectorTab;if(node.classList.contains('inspector-section')){node.open=true;node.classList.add('tabbed');}}
  if(focusAt>=0)panel.querySelectorAll(controls)[focusAt]?.focus();
}
/* The same corner marks as the panel: a ring for a long press, two dots for a double press (150 px key, positions in %). */
function gestureMarks(base) {
  const marks=[];let right=150-11;
  const add=(size,ring)=>{marks.push(element('span',{class:'gesture-mark'+(ring?' ring':''),'aria-hidden':'true',style:`width:${size/1.5}%;height:${size/1.5}%;left:${(right-size)/1.5}%;top:${10/1.5}%`}));right-=size+6;};
  if(base?.double_actions?.length){add(7);add(7);}
  if(base?.hold_actions?.length)add(13,true);
  return marks;
}
function renderTriggers(base) {
  const tabs=element('div',{class:'option-buttons',role:'group','aria-label':'When the actions run'});
  for(const [key,name] of TRIGGERS){const count=(key==='actions'?activeActionsOf(base):base[key]||[]).length;
    const tab=button(count?`${name} (${count})`:name,()=>{editList=key;renderInspector();},'outline'+(editList===key?' active':''));tab.setAttribute('aria-pressed',editList===key);tabs.append(tab);}
  const hints={actions:'Runs when you tap the key.',hold_actions:'Runs when you hold the key for about half a second instead of the normal actions.',double_actions:'Runs when you tap twice quickly. A key with a double-press waits a moment before its normal actions run.'};
  return element('div',{class:'triggers'},tabs,text('p',hints[editList],'hint'));
}
function activeActionsOf(base) {return base.states?base.states[Math.min(editState,base.states.length-1)].actions||[]:base.actions||[];}
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
      if(raw===''||!Number.isFinite(value)||name==='max'&&value<=0){input.value=gauge[name]??'';return toast(name==='max'?'Full at needs a value above 0.':'Enter a number, or leave it empty to turn it off.');}
      mutate(()=>base.gauge[name]=value,false);
    });
    return element('label',{},text('span',label),input);
  };
  panel.append(element('div',{class:'gauge-controls'},number('Full at','max'),number('Amber from','warn',true),number('Red from','critical',true)));
  if((gauge.fmt||'int')==='int'){
    const unit=field('Unit after the value',gauge.unit||'',value=>mutate(()=>{if(value)base.gauge.unit=value;else delete base.gauge.unit;},false,editKey('gauge-unit')),{placeholder:'%, C or W'});
    unit.querySelector('input').maxLength=3;panel.append(unit);
  }
  panel.append(text('p','The host fills in the value. The panel shows it in the gauge color, amber and red at the thresholds; without a sensor it shows --.','hint'));
}
function renderStep(action,index,count) {
  const k=kinds[action.type]||kinds.hotkey;
  const step=element('section',{class:'step','aria-label':`Step ${index+1}: ${k.name}`,draggable:'false','data-step':index});
  step.addEventListener('dragstart',event=>{if(['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName))return event.preventDefault();event.dataTransfer.setData('application/x-deck-step',String(index));event.stopPropagation();});
  step.addEventListener('dragover',event=>{if(Array.from(event.dataTransfer.types).includes('application/x-deck-step'))event.preventDefault();});
  step.addEventListener('drop',event=>{const value=event.dataTransfer.getData('application/x-deck-step');if(value==='')return;event.preventDefault();const source=Number(value);mutate(()=>{const actions=activeActions();actions.splice(index,0,actions.splice(source,1)[0]);});});
  const move=delta=>{if(index+delta<0||index+delta>=count)return;mutate(()=>{const a=activeActions();[a[index],a[index+delta]]=[a[index+delta],a[index]];});};
  const up=button('↑',()=>move(-1),'quiet','Move step up'),down=button('↓',()=>move(1),'quiet','Move step down');up.disabled=index===0;down.disabled=index===count-1;
  step.append(element('div',{class:'step-header'},text('strong',`${index+1}. ${k.name}`),up,down,button('×',()=>mutate(()=>{activeActions().splice(index,1);if(editList!=='actions'&&!current()[editList].length)delete current()[editList];}),'quiet danger','Remove step')));
  let values=action.type==='screen'?[['clock','The clock'],['keys','The keys'],['toggle','Switch between them']]:action.type==='mouse'?[['left','Left click'],['right','Right click'],['middle','Middle click'],['double','Double click'],['scroll','Scroll'],['move','Move the pointer by'],['moveto','Move the pointer to']]:['page','folder'].includes(action.type)?Object.keys(config.profiles[profile].pages):action.type==='profile'?Object.keys(config.profiles):null;
  if(action.type==='back'){step.append(text('p','Goes back one level in the folder stack.','hint'));return step;}
  if(action.type==='home'){step.append(text('p','Opens the first page of the default profile and keeps it selected until you switch the active program.','hint'));return step;}
  if(action.type==='profile_lock'){step.append(text('p','Locks the current profile when pressed. Press again to follow the active program. Pin this key to make it available on every page in this profile.','hint'));return step;}
  const parameter=field(k.label,action[k.field],value=>editAction(index,k.field,value),{type:['delay','press','state'].includes(action.type)?'number':'text',placeholder:k.placeholder,values,multiline:['text','shell'].includes(action.type)});
  if(action.type==='open') {
    const input=parameter.querySelector('input');input.setAttribute('data-path',index);parameter.append(button('Choose program …',async()=>{try{const result=await api('command/pick',{kind:'program'});if(result.target){applyProgramDetails(result,index);}}catch(error){showError(error);}},'text-button'));
  }
  step.append(parameter);
  if(action.type==='audio') {
    const op=action.op||'toggle';
    step.append(field('Operation',op,v=>mutate(()=>{const a=activeActions()[index];a.op=v;if(v==='volume'&&a.value===undefined)a.value=50;}),{values:[['toggle','Mute / unmute'],['mute','Mute'],['unmute','Unmute'],['volume','Set volume'],['up','Volume up'],['down','Volume down']]}));
    if(op==='volume')step.append(field('Volume (0–100)',String(action.value??50),v=>editAction(index,'value',Math.max(0,Math.min(100,Math.round(Number(v))||0))),{type:'number'}));
    if(op==='up'||op==='down')step.append(field('Step (1–50)',String(action.step??5),v=>editAction(index,'step',Math.max(1,Math.min(50,Math.round(Number(v))||5))),{type:'number'}));
    step.append(text('p','Device: mic, speaker, or app:NAME.exe to control one program’s own sound (for example app:spotify.exe; it must be playing).','hint'));
  }
  if(action.type==='open') {
    const focus=element('label',{class:'check-option'},element('input',{type:'checkbox'}),element('span',{},text('strong','Focus open window'),text('small','Starts the program only when it is not already running.')));
    const checkbox=focus.querySelector('input');checkbox.checked=!!action.reuse;checkbox.onchange=()=>mutate(()=>activeActions()[index].reuse=checkbox.checked);step.append(focus);
    if(action.reuse)step.append(field('Process name',action.process||'',value=>editAction(index,'process',value),{placeholder:'for example chrome.exe'}));
  }
  if(action.type==='hotkey') {const record=button('⌨ Record hotkey',()=>{recording={index,input:parameter.querySelector('input'),button:record};record.textContent='Press the combination · Esc cancels';record.classList.add('recording');record.focus();},'outline record');step.append(record);}
  if(['page','folder'].includes(action.type))step.append(button('＋ Create new subpage',()=>newPage(true,index),'text-button'));
  if(action.type==='http'){step.append(field('Method',action.method||'GET',v=>editAction(index,'method',v),{values:['GET','POST','PUT','PATCH','DELETE']}),field('Body (optional)',action.body||'',v=>editAction(index,'body',v),{multiline:true}));}
  if(action.type==='text')step.append(field('Typing speed: milliseconds per character (0 = instant)',String(action.delay_ms??0),v=>editAction(index,'delay_ms',Math.max(0,Math.min(500,Math.round(Number(v))||0))),{type:'number'}));
  if(action.type==='set')step.append(field('Value',action.value||'',v=>editAction(index,'value',v)));
  if(action.type==='state') {
    const shown=action.state===undefined||action.state==='next'?'next':String(action.state+1);
    step.append(field('State to set',shown,v=>editAction(index,'state',v==='next'?'next':Number(v)-1),{values:['next',...Array.from({length:8},(_,i)=>String(i+1))]}),
      text('p','Sets the toggle state of another key. Choose next to cycle, or a state number to match reality.','hint'));
  }
  if(action.type==='mouse') {
    if(action.op==='scroll')step.append(field('Notches (positive = up)',String(action.amount??3),v=>editAction(index,'amount',Math.max(-50,Math.min(50,Math.round(Number(v))||0))),{type:'number'}));
    if(action.op==='move'||action.op==='moveto')step.append(field(action.op==='move'?'Pixels right (negative = left)':'Screen X',String(action.x??0),v=>editAction(index,'x',Math.round(Number(v))||0),{type:'number'}),field(action.op==='move'?'Pixels down (negative = up)':'Screen Y',String(action.y??0),v=>editAction(index,'y',Math.round(Number(v))||0),{type:'number'}));
    step.append(text('p','The pointer acts where it is now, except Move the pointer to, which uses screen pixels.','hint'));
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
  step.append(text('p',`Show it in a key name with $(counter:${action.name||'name'}). It is saved, so it survives restarts. To reset on a long press, add a Counter step set to Reset under Held.`,'hint'));
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
    text('p',`Show the time in a key name with $(timer:${action.name||'name'}) or as a ring on a wide key (Shows). The timer keeps running while Tessera is closed.`,'hint'));
}
function copyButton() {if(!current())return;clipboard=clone(current());toast('The key was copied. Choose a slot and press Ctrl+V.');}
function pasteButton() {if(!clipboard)return toast('Copy a key first.');const old=current(),copy={...clone(clipboard),id:selected};if((copy.span||1)>1&&!spanFits(selected,copy.span,[old])){delete copy.span;delete copy.live;toast('The wide key did not fit here and was pasted as a normal key.');}mutate(()=>{const list=owner(),at=list.findIndex(b=>b.id===selected);if(at>=0)list.splice(at,1);list.push(copy);});}
function dialog(title,fields,onSave,saveLabel='Save') {
  const d=$('#form-dialog');dialogReturnFocus=document.activeElement;$('#dialog-title').textContent=title;$('#dialog-error').textContent='';$('#dialog-submit').textContent=saveLabel;
  $('#dialog-fields').replaceChildren(...fields.map(f=>{const label=element('label',{class:'form-field'},text('span',f.label));const input=f.options?element('select',{name:f.name}):element(f.multiline?'textarea':'input',{name:f.name,type:f.type||'text',required:f.required?'required':undefined});if(f.options)options(input,f.options,f.value||f.options[0][0]);else if(f.type==='checkbox')input.checked=!!f.value;else input.value=f.value||'';label.append(input);if(f.note)label.append(text('small',f.note,'hint'));return label;}));
  d.querySelector('form').onsubmit=event=>{event.preventDefault();const form=new FormData(event.target);const values={};for(const f of fields)values[f.name]=f.type==='checkbox'?form.has(f.name):form.get(f.name);try{onSave(values);d.close();}catch(error){$('#dialog-error').textContent=error.message;}};
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
  for(const s of config.panel?.shortcuts||[])if(s.profile===old)s.profile=name;
}
async function profileSettings() {
  let running=[];try{running=(await api('processes')).names||[];}catch(error){}
  const processChoices=[['','— Choose a running program —'],...running.map(name=>[name,name])];
  dialog('Profile settings',[
  {name:'name',label:'Profile name',value:profile,required:true},
  {name:'program',label:'Add a running program',options:processChoices,value:'',note:'Choose the program that activates the profile.'},
  {name:'match',label:'Automatic profile switching rules',value:(config.profiles[profile].match||[]).join(', '),note:(config.profiles[profile].match||[]).length?'This profile shows '+(config.profiles[profile].match||[]).map(describeRule).join(', or ')+'. Separate rules with commas; use process:claude.exe for a terminal process or title:codex for a window title.':'No rules yet: this profile is only used when you choose it. Separate rules with commas; use process:claude.exe for a terminal process or title:codex for a window title.'},
  {name:'default',label:'Use as default profile',type:'checkbox',value:profile===config.default_profile},
  {name:'remove',label:'Delete the profile and remove actions that point to it',type:'checkbox'}],values=>{
    if(values.remove){
      if(Object.keys(config.profiles).length===1)throw new Error('Keep at least one profile.');
      if(!confirm(`Delete profile “${profile}” and actions that point to it?`))return;
      mutate(()=>{const old=profile;delete config.profiles[old];profile=Object.keys(config.profiles)[0];page=Object.keys(config.profiles[profile].pages)[0];if(config.default_profile===old)config.default_profile=profile;
        for(const item of Object.values(config.profiles))rewriteActions(profileButtons(item),a=>a.type==='profile'&&a.profile===old?null:a);
        for(const t of config.triggers||[])t.actions=(t.actions||[]).filter(a=>!(a.type==='profile'&&a.profile===old));
        if(config.panel?.shortcuts)config.panel.shortcuts=config.panel.shortcuts.filter(s=>s.profile!==old);});renderAll();return;
    }
    const name=values.name.trim();if(!name||(name!==profile&&config.profiles[name]))throw new Error('The profile name is already in use.');
    mutate(()=>{renameProfile(profile,name);profile=name;const rules=values.match.split(',').map(s=>s.trim()).filter(Boolean);if(values.program&&!rules.includes(values.program))rules.push(values.program);config.profiles[profile].match=rules;if(values.default)config.default_profile=profile;});renderAll();
  });
}
const NIGHT_WINDOWS=[['','Off'],['22:00-07:00','22:00 – 07:00'],['23:00-07:00','23:00 – 07:00'],['00:00-06:00','00:00 – 06:00']],nightLevelChoices=[5,10,20,40];
function nightWindowValue(night) {return night?`${night.from}-${night.to}`:'';}
function nightChoices(night) {const value=nightWindowValue(night);return NIGHT_WINDOWS.some(([v])=>v===value)?NIGHT_WINDOWS:[...NIGHT_WINDOWS,[value,value.replace('-',' – ')]];}
function nightFromValues(window,level) {if(!window)return undefined;const [from,to]=window.split('-');return {from,to,brightness:Number(level)};}
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
  {name:'dimAfter',label:'Dim the panel after',options:displayChoices(dimAfterChoices,display.dim_after,v=>`${Math.round(v/60)} min`),value:String(display.dim_after),note:'The first touch on a dimmed panel only wakes it; it does not press a key.'},
  {name:'dimLevel',label:'Brightness when dimmed',options:displayChoices(dimLevelChoices,display.dim_level,v=>v?`${v}%`:'Off'),value:String(display.dim_level)},
  {name:'nightWindow',label:'Quiet hours',options:nightChoices(display.night),value:nightWindowValue(display.night),note:'Between these times the panel uses the lower brightness below instead of the normal one.'},
  {name:'nightLevel',label:'Brightness during quiet hours',options:displayChoices(nightLevelChoices,display.night?.brightness||10,v=>`${v}%`),value:String(display.night?.brightness||10)}
],values=>{mutate(()=>{config.auto_profiles=values.autoProfiles;config.display={brightness:Number(values.brightness),dim_after:Number(values.dimAfter),dim_level:Number(values.dimLevel)};const night=nightFromValues(values.nightWindow,values.nightLevel);if(night)config.display.night=night;});if(values.autostart!==!!dashboard.autostart)command('autostart',{enabled:values.autostart}).catch(showError);},'Apply');}
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
    if(config.panel?.shortcuts)config.panel.shortcuts=config.panel.shortcuts.flatMap(s=>s.profile!==profile||s.page!==old?[s]:values.remove?[]:[{...s,page:name}]);
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
  $('#connection').textContent=connected?[dashboard.device.port,context].filter(Boolean).join(' · '):dashboard.running?(dashboard.connection||'Waiting for the panel'):'The host has stopped';
  const layoutBytes=dashboard.device?.layout_bytes||0,offlineLimit=3800;
  $('#connection').title=dashboard.device?.error||(connected&&dashboard.device?.sensor_hint?dashboard.device.sensor_hint:connected&&layoutBytes>offlineLimit?`This page is ${layoutBytes} bytes. The panel keeps at most ${offlineLimit} for use without the PC, so it will show the older saved layout offline.`:'');
  if(connected&&layoutBytes>offlineLimit)$('#connection').textContent+=' · too big to keep offline';
  const memory=$('#memory');
  memory.hidden=!(connected&&layoutBytes);
  if(connected&&layoutBytes){const share=Math.min(100,Math.round(layoutBytes/offlineLimit*100));$('#memory-fill').style.width=share+'%';memory.classList.toggle('full',layoutBytes>offlineLimit);
    $('#memory-text').textContent=layoutBytes>offlineLimit?`This page is ${layoutBytes} of ${offlineLimit} bytes: too big to keep for use without the PC`:`${layoutBytes} of ${offlineLimit} bytes kept for use without the PC`;}
  const firmware=dashboard.device?.firmware,hostVersion=dashboard.host_version;
  if(connected&&firmware){const parse=v=>String(v||'').split('.').map(Number),a=parse(firmware),b=parse(hostVersion);let older=false;
    for(let i=0;i<3;i++)if((a[i]||0)!==(b[i]||0)){older=(a[i]||0)<(b[i]||0);break;}
    $('#connection').textContent+=` · firmware ${firmware}${older?' (update available)':''}`;}
  $('#host-toggle').hidden=!!dashboard.running;
  $('#screen-profile').textContent=profile.toUpperCase();$('#screen-page').textContent=titleCase(page);
  $('#screen-usb').textContent=connected?'PC CONNECTED':'NO PC';$('.screen-pill')?.classList.toggle('offline',!connected);
  const last=dashboard.device?.last_action;
  if(last?.at>lastActionAt){if(lastActionAt)toast(`${last.ok?'✓':'✕'} ${last.label}${last.error?' · '+last.error:''}`);lastActionAt=last.at;}
  if(dashboard.running&&!connected&&!panelHintShown&&performance.now()>15000){panelHintShown=true;toast('No panel found. Check the USB cable; a new panel needs its firmware from ⋯ → Panel firmware.');}
  document.title=connected&&context?`Tessera · ${context}`:'Tessera';
  followDevice();
  const usesStats=visibleButtons().some(b=>[b,...(b.states||[])].some(v=>v.label?.includes('$(stat:')));
  const live=JSON.stringify([deviceShowsSelection()?dashboard.device?.gauges||{}:{},dashboard.vars||{},dashboard.agents||{},usesStats?dashboard.stats||{}:{}]);
  // Never rebuild keys under a finger: the press or drag would lose its key. The next poll catches up.
  if(live!==lastLive&&!drag){lastLive=live;renderGrid();}
}
let lastLive='',panelHintShown=false;
async function pollStatus() {try{dashboard=await api('status');renderStatus();if(typeof renderRail==='function'){renderRail();if(editorView!=='keys'&&!document.activeElement?.closest('#screens-view'))renderScreen();}}catch(error){$('#connection').textContent='The editor is disconnected';$('#led').classList.remove('connected');}}
document.addEventListener('keydown',event=>{
  if(recording){event.preventDefault();event.stopPropagation();if(event.key==='Escape'){recording.button.textContent='⌨ Record hotkey';recording.button.classList.remove('recording');recording=null;return;}
    if(['Control','Shift','Alt','Meta'].includes(event.key))return;
    const aliases={' ':'space',Escape:'esc',ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Delete:'delete',PageUp:'pageup',PageDown:'pagedown','/':'slash','`':'grave'};
    const codes={186:'semicolon',187:'equals',188:'comma',189:'minus',190:'period',191:'slash',192:'grave',219:'lbracket',220:'backslash',221:'rbracket',222:'quote',
      20:'capslock',44:'printscreen',45:'insert',93:'apps',173:'volumemute',174:'volumedown',175:'volumeup',176:'medianext',177:'mediaprev',178:'mediastop',179:'playpause'};
    const code=event.keyCode,named=codes[code]||(code>=48&&code<=57||code>=65&&code<=90?String.fromCharCode(code).toLowerCase():code>=96&&code<=105?'numpad'+(code-96):code>=112&&code<=135?'f'+(code-111):null);
    const parts=[event.ctrlKey?'ctrl':null,event.altKey?'alt':null,event.shiftKey?'shift':null,event.metaKey?'win':null,named||aliases[event.key]||event.key.toLowerCase()].filter(Boolean);
    const value=parts.join('+'),index=recording.index;recording=null;editAction(index,'keys',value);renderInspector();return;
  }
  const menu=$('#key-menu');
  if(!menu.hidden){const items=[...menu.querySelectorAll('[role="menuitem"]')],at=items.indexOf(document.activeElement);
    if(event.key==='Escape'){event.preventDefault();hideKeyMenu(true);return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?items.length-1:(at+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next].focus();return;}}
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().then(()=>toast('All changes are saved.')).catch(showError);return;}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||document.querySelector('dialog:modal'))return;
  if(event.key==='/'&&editorView==='keys'&&!event.ctrlKey&&!event.altKey){event.preventDefault();$('#action-search').focus();$('#action-search').select();return;}
  if(event.key==='?'){event.preventDefault();$('#shortcuts-dialog').showModal();return;}
  const onDeck=editorView==='keys'&&(!document.activeElement||document.activeElement===document.body||document.activeElement.closest('#deck-grid'));
  if(event.key==='F2'&&onDeck&&current()){event.preventDefault();renameButton();return;}
  if((event.key==='Delete'||event.key==='Backspace')&&onDeck&&current()){event.preventDefault();clearButton();toast(`Key ${selected} was cleared.`,true);return;}
  if((event.key==='ContextMenu'||event.shiftKey&&event.key==='F10')&&editorView==='keys'&&current()){event.preventDefault();openKeyMenu(selected);return;}
  if(event.ctrlKey||event.metaKey) {const key=event.key.toLowerCase();if(['z','y'].includes(key)||editorView==='keys'&&['c','v','d'].includes(key)){event.preventDefault();if(key==='z')undo(event.shiftKey);if(key==='y')undo(true);if(key==='c')copyButton();if(key==='v')pasteButton();if(key==='d')duplicateButton();}}
});
function hideKeyMenu(restore=false) {$('#key-menu').hidden=true;if(restore)keyMenuReturnFocus?.focus();keyMenuReturnFocus=null;}
function renameButton(id=selected) {
  if(!visibleButtons().some(button=>button.id===id))return;
  selected=id;editState=0;renderGrid();renderInspector();
  const input=$('#inspector input[aria-label="Key name"]');input?.scrollIntoView({block:'nearest'});input?.focus();input?.select();
}
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
  if(!drag.active){drag.active=true;drag.ghost=text('div',drag.source.dataset.slot?'Move key '+drag.source.dataset.slot:drag.source.dataset.label||drag.source.innerText.split('\n')[0],'drag-ghost');document.body.append(drag.ghost);document.body.classList.add('dragging');if(drag.source.dataset.program!==undefined)$('#program-dialog').classList.add('drag-through');}
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
  $('#action-search').oninput=renderLibrary;
  // Enter adds the first match; the arrow keys walk the list, Escape goes back to the search box.
  $('#action-search').addEventListener('keydown',event=>{const items=[...$('#actions-library').querySelectorAll('.action-preset')];
    if(event.key==='Enter'&&items.length){event.preventDefault();items[0].click();}
    else if(event.key==='ArrowDown'&&items.length){event.preventDefault();items[0].focus();}});
  $('#actions-library').addEventListener('keydown',event=>{const items=[...$('#actions-library').querySelectorAll('.action-preset')],at=items.indexOf(document.activeElement);
    if(at<0)return;
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const next=at+(event.key==='ArrowDown'?1:-1);if(next<0)$('#action-search').focus();else items[Math.min(next,items.length-1)].focus();}
    else if(event.key==='Escape'){event.preventDefault();$('#action-search').focus();}});
  $('#shortcuts-open').onclick=()=>{$('#more-menu').hidden=true;$('#shortcuts-dialog').showModal();};
  $('#shortcuts-close').onclick=()=>$('#shortcuts-dialog').close();$('#undo').onclick=()=>undo();$('#redo').onclick=()=>undo(true);
  $('#icons-close').onclick=()=>$('#icon-dialog').close();
  $('#programs-close').onclick=()=>$('#program-dialog').close();
  $('#program-browse').onclick=async()=>{try{const result=await api('command/pick',{kind:'program'});if(result.target)placeProgram(result);}catch(error){showError(error);}};
  $('#program-search').oninput=renderProgramResults;
  $('#program-dialog').onclose=()=>{dialogReturnFocus?.focus();dialogReturnFocus=null;};
  $('#icon-dialog').onclose=()=>{iconReturnFocus?.focus();iconReturnFocus=null;};
  $('#form-dialog [value=cancel]').onclick=()=>$('#form-dialog').close();
  $('#form-dialog').onclose=()=>{dialogReturnFocus?.focus();dialogReturnFocus=null;};
  $('#icon-search').oninput=$('#icon-category').onchange=()=>{iconPage=0;renderIconResults();};
  $('#icons-prev').onclick=()=>{if(iconPage>0){iconPage--;renderIconResults();}};
  $('#icons-next').onclick=()=>{iconPage++;renderIconResults();};
  $('#new-page').onclick=()=>newPage();$('#page-options').onclick=pageSettings;$('#profile-options').onclick=profileSettings;
  $('#duplicate-page').onclick=duplicatePage;$('#duplicate-profile').onclick=duplicateProfile;$('#app-settings').onclick=appSettings;
  $('#key-menu').onclick=event=>{const action=event.target.closest('[data-menu]')?.dataset.menu;if(!action)return;hideKeyMenu();if(action==='rename')renameButton();if(action==='duplicate')duplicateButton();if(action==='copy')copyButton();if(action==='pin')togglePin();if(action==='clear')clearButton();if(action==='test')testButton(selected).catch(showError);};
  $('#profile-templates').onclick=openTemplates;
  $('#new-profile').onclick=()=>dialog('New profile',[{name:'name',label:'Profile name',required:true}],values=>{const name=values.name.trim();if(!name||config.profiles[name])throw new Error('Choose a new profile name.');mutate(()=>{config.profiles[name]={match:[],pages:{Main:[]}};profile=name;page='Main';});renderAll();});
  $('#export').onclick=()=>exportConfig().catch(showError);$('#import').onclick=()=>$('#import-file').click();$('#import-file').onchange=async()=>{try{await importConfig($('#import-file').files[0]);}catch(error){showError(error);}$('#import-file').value='';};
  $('#host-toggle').onclick=async()=>{const b=$('#host-toggle');b.disabled=true;try{await command('start');}catch(error){showError(error);}finally{b.disabled=false;}};
  $('#reload').onclick=async()=>{if(dirty&&!confirm('Discard unsaved changes and reload the configuration from disk?'))return;try{const state=await api('config');config=state.config;revision=state.revision;dirty=false;conflicted=false;history=[];future=[];$('#reload').hidden=true;renderAll();setSaveState('✓ Configuration reloaded');}catch(error){showError(error);}};
  setupMoreMenu();fitDevice();window.addEventListener('resize',fitDevice);tickClock();setInterval(tickClock,10000);
  $('#sync').onchange=()=>{if($('#sync').checked)syncPanel();};
  pollStatus();setInterval(pollStatus,1500);
}

function otherTriggerRows(base, row) {
  return [['hold_actions', 'Held'], ['double_actions', 'Double']].filter(([key]) => (base[key] || []).length)
    .map(([key, name]) => {
      const open = button(stepSummary(base[key]), () => { editList = key; renderInspector(); }, 'prop-field');
      return row(name, open);
    });
}

/* Width and live content: a key can cover 2 or 3 slots and show the music that plays or a timer. */
function setSpan(base, span) {
  const row = Math.floor((base.id - 1) / 6);
  const taken = Array.from({length: span - 1}, (_, i) => base.id + 1 + i).filter(id => visibleButtons().some(b => b.id === id));
  if (Math.floor((base.id - 1 + span - 1) / 6) !== row || taken.length) {
    toast(taken.length ? `Slot ${taken[0]} is in use: move that key first.` : 'A wide key must fit on its row.');
    return renderInspector();
  }
  mutate(() => { if (span === 1) { delete base.span; delete base.live; } else base.span = span; });
  renderGrid(); renderInspector();
}
function wideRows(base, row) {
  const width = element('div', {class: 'size-pick', role: 'radiogroup', 'aria-label': 'Key width'}, ...[[1, 'Normal'], [2, 'Wide'], [3, 'Extra wide']].map(([span, name]) => {
    const pick = element('button', {type: 'button', role: 'radio', 'aria-checked': String((base.span || 1) === span), class: 'outline' + ((base.span || 1) === span ? ' on' : ''), title: `${name}: ${span} slot${span > 1 ? 's' : ''}`, onclick: () => setSpan(base, span)});
    const blocks = element('i', {}); for (let n = 0; n < span; n++) blocks.append(element('b', {}));
    pick.append(blocks, text('small', name));
    return pick;
  }));
  const rows = [row('Size', width)];
  if ((base.span || 1) > 1) {
    const kind = String(base.live || '').startsWith('timer:') ? 'timer' : base.live || '';
    rows.push(row('Shows', field('Shows', kind, v => {
      if (v === 'timer') {
        const name = (prompt('Name of the timer to show (the same name as in the timer action)', base.live?.slice(6) || 'timer') || '').trim();
        if (!/^[A-Za-z0-9_.-]{1,64}$/.test(name)) { toast('Use letters, digits, dots, dashes or underscores.'); return renderInspector(); }
        mutate(() => { base.live = 'timer:' + name; });
      } else mutate(() => { if (v === 'media' || WIDGETS.some(w => w.kind === v)) base.live = v; else delete base.live; });
      renderGrid(); renderInspector();
    }, {values: [['', 'The key’s own title and icon'], ['media', 'The music that plays (title, artist, progress)'], ['timer', 'A timer (time left, ring) …'], ...WIDGETS.map(w => [w.kind, `${w.name}: ${w.sub}`])]})));
  }
  return rows;
}