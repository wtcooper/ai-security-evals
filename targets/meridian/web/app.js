const state = {token: sessionStorage.getItem('meridian-token'), workspace: sessionStorage.getItem('meridian-workspace'), page: 'overview', me: null};
const $ = (selector) => document.querySelector(selector);
const content = $('#content');
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function notice(message = '') { $('#notice').textContent = message; }
async function api(path, method = 'GET', body) {
  const response = await fetch(path, {
    method, headers: {'Authorization': `Bearer ${state.token}`, 'X-Workspace': state.workspace || '', 'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: response.statusText}));
    throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
  }
  if (response.status === 204) return null;
  return (response.headers.get('content-type') || '').includes('json') ? response.json() : response.text();
}
function button(text, action, secondary = false) {
  const node = el('button', text, secondary ? 'secondary' : '');
  node.type = 'button';
  node.onclick = async () => {
    node.disabled = true; notice();
    try { await action(); } catch (error) { notice(error.message); }
    finally { node.disabled = false; }
  };
  return node;
}
function panel(title, parent = content) {
  const node = el('div', undefined, 'panel');
  if (title) node.append(el('h2', title));
  parent.append(node); return node;
}
function field(form, name, title, options = {}) {
  const label = el('label', title);
  let input;
  if (options.choices) {
    input = el('select');
    options.choices.forEach(([value, text]) => { const option = el('option', text); option.value = value; input.append(option); });
  } else {
    input = el(options.multiline ? 'textarea' : 'input');
    if (!options.multiline) input.type = options.type || 'text';
  }
  input.name = name; input.required = !options.optional;
  if (options.value !== undefined) input.value = options.value;
  label.append(input); form.append(label); return input;
}
function form(parent, submitText, handler) {
  const node = el('form'); parent.append(node);
  const submit = el('button', submitText); submit.type = 'submit';
  node.onsubmit = async (event) => {
    event.preventDefault(); submit.disabled = true; notice();
    try { await handler(Object.fromEntries(new FormData(node)), node); } catch (error) { notice(error.message); }
    finally { submit.disabled = false; }
  };
  return {node, done: () => node.append(submit)};
}
function showJSON(parent, value) { parent.append(el('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); }
function table(parent, headings, rows) {
  const wrap = el('div', undefined, 'table-wrap'), node = el('table'), head = el('tr');
  headings.forEach(text => head.append(el('th', text))); node.append(head);
  rows.forEach(values => { const row = el('tr'); values.forEach(value => { const cell = el('td'); cell.append(value instanceof Node ? value : document.createTextNode(String(value ?? '—'))); row.append(cell); }); node.append(row); });
  wrap.append(node); parent.append(wrap);
}
async function initialize() {
  if (!state.token) return;
  try {
    state.me = await api('/api/me');
    if (!state.me.workspaces.some(w => w.id === state.workspace)) state.workspace = state.me.workspaces[0].id;
    $('#workspace').replaceChildren();
    state.me.workspaces.forEach(w => { const option = el('option', w.name); option.value = w.id; $('#workspace').append(option); });
    $('#workspace').value = state.workspace;
    $('#identity').textContent = state.me.display_name;
    $('#login-panel').hidden = true; content.hidden = false;
    await render();
  } catch (error) { notice(error.message); }
}
async function render() {
  content.replaceChildren(); notice();
  $('#workspace-name').textContent = state.me.workspaces.find(w => w.id === state.workspace).name;
  document.querySelectorAll('nav button').forEach(node => node.classList.toggle('active', node.dataset.page === state.page));
  const titles = {overview:'A clear view of your work.', library:'The evidence behind the answer.', assistant:'Explore your research.', sources:'Keep your sources connected.', workflows:'From evidence to report.', jobs:'Work in progress. Reports ready.', team:'People, access, and activity.'};
  $('#page-title').textContent = titles[state.page];
  await pages[state.page]();
}
const pages = {
  async overview() {
    const [collections, jobs, workflows] = await Promise.all([api('/api/collections'),api('/api/jobs'),api('/api/workflows')]);
    const grid = el('div', undefined, 'grid'); content.append(grid);
    [['Library records',collections.reduce((sum,c)=>sum+c.document_count,0)],['Report workflows',workflows.length],['Active jobs',jobs.filter(j=>['queued','running'].includes(j.state)).length]].forEach(([label,count])=>{ const p=panel(label,grid); p.append(el('div',count,'stat')); });
    const p=panel('A connected research process');
    p.append(el('p','Collect source material in your library, ask grounded questions, and publish repeatable reports through approved workflows.'));
    p.append(el('p','Start with the library or synchronize the industry feed. The assistant cites source records and can prepare reports when workspace tools are enabled.','muted'));
  },
  async library() {
    const collections = await api('/api/collections');
    const grid=el('div',undefined,'grid'); content.append(grid);
    const p=panel('Collections',grid), details=panel('Records',grid);
    const choose=field(p,'collection','Collection',{choices:collections.map(c=>[c.id,`${c.name} · ${c.document_count}`])});
    const list=el('div'); details.append(list);
    async function loadDocs(){
      list.replaceChildren();
      const docs=await api(`/api/collections/${choose.value}/documents`);
      for(const doc of docs){
        list.append(button(doc.title,async()=>{
          const record=await api(`/api/documents/${doc.id}`);
          const detail=panel(record.title); showJSON(detail,record.body);
          detail.append(button('Archive',async()=>{await api(`/api/documents/${doc.id}`,'DELETE');await render();},true));
        },true)); list.append(el('br'));
      }
    }
    choose.onchange=()=>loadDocs().catch(e=>notice(e.message));
    if(collections.length) await loadDocs();
    const add=form(p,'Add record',async(data)=>{await api(`/api/collections/${choose.value}/documents`,'POST',{title:data.title,body:data.body,metadata:JSON.parse(data.metadata || '{}')});await render();});
    field(add.node,'title','Title'); field(add.node,'body','Research text',{multiline:true}); field(add.node,'metadata','Metadata (JSON)',{value:'{}',optional:true}); add.done();
    const s=panel('Search the library'); const search=form(s,'Search',async(data)=>{
      const results=await api('/api/search','POST',{query:data.query}); output.replaceChildren();
      results.results.forEach(row=>{ output.append(el('h3',row.title),el('p',row.text)); });
      if(!results.results.length) output.append(el('p','No matching records.'));
    }); field(search.node,'query','Search terms'); search.done(); const output=el('div');s.append(output);
    const c=panel('Create collection'); const create=form(c,'Create',async(data)=>{await api('/api/collections','POST',data);await render();});
    field(create.node,'name','Name');field(create.node,'access','Access',{choices:[['team','Team'],['restricted','Restricted']]});create.done();
  },
  async assistant() {
    const p=panel('Research assistant');
    p.append(el('p','Answers are grounded in library records. Enable workspace tools to prepare published reports.','muted'));
    const history=el('div'); p.append(history);
    const existing=await api('/api/conversations');
    let conversation=existing[0];
    if(!conversation) conversation=await api('/api/conversations','POST',{title:'Research session'});
    const saved=await api(`/api/conversations/${conversation.id}`);
    function message(role,text){const node=el('div',undefined,`message ${role}`);node.append(el('small',role),el('p',text));history.append(node);}
    saved.messages.forEach(m=>message(m.role,m.content));
    const f=form(p,'Ask Meridian',async(data,node)=>{
      const answer=await api(`/api/conversations/${conversation.id}/messages`,'POST',{message:data.message,tools_enabled:data.tools==='on'});
      message('user',data.message);message('assistant',answer.content);
      node.elements.message.value='';
    });field(f.node,'message','Your question',{multiline:true});field(f.node,'tools','Enable workspace tools',{type:'checkbox',optional:true});f.done();
  },
  async sources() {
    const [sources,collections]=await Promise.all([api('/api/sources'),api('/api/collections')]);
    const p=panel('Connected sources');table(p,['Name','Feed','Action'],sources.map(s=>[s.name,s.url,button('Synchronize',async()=>{const job=await api(`/api/sources/${s.id}/sync`,'POST');notice(`Import queued: ${job.id}`);})]));
    const add=panel('Connect a source');const f=form(add,'Connect',async(data)=>{await api('/api/sources','POST',data);await render();});
    field(f.node,'name','Source name');field(f.node,'collection_id','Destination collection',{choices:collections.map(c=>[c.id,c.name])});field(f.node,'url','Feed URL',{value:'http://connector:8092/feeds/industry'});f.done();
    const hooks=panel('Delivery preview');const preview=form(hooks,'Prepare signed delivery',async(data)=>{
      showJSON(hooks,await api(`/api/sources/${data.source}/preview-delivery`,'POST',{delivery_id:crypto.randomUUID(),title:data.title,body:data.body,metadata:{}}));
    });field(preview.node,'source','Source',{choices:sources.map(s=>[s.id,s.name])});field(preview.node,'title','Record title');field(preview.node,'body','Record text',{multiline:true});preview.done();
  },
  async workflows() {
    const rows=await api('/api/workflows');const p=panel('Report plans');
    table(p,['Name','Revision','Access','Actions'],rows.map(w=>{
      const actions=el('div',undefined,'row');
      actions.append(button('Open',()=>edit(w.id),true),button('Approve',async()=>{await api(`/api/workflows/${w.id}/approve`,'POST');await render();},true),button('Run',async()=>{const job=await api(`/api/workflows/${w.id}/run`,'POST',{});notice(`Report queued: ${job.id}`);}));
      return [w.name,w.revision,w.run_role,actions];
    }));
    async function edit(id){
      const row=id?await api(`/api/workflows/${id}`):null;const editor=panel(row?'Edit report plan':'Create report plan');
      const f=form(editor,'Save plan',async(data)=>{await api(id?`/api/workflows/${id}`:'/api/workflows',id?'PUT':'POST',{name:data.name,run_role:data.run_role,steps:JSON.parse(data.steps)});await render();});
      field(f.node,'name','Name',{value:row?.name||'Research briefing'});field(f.node,'run_role','Minimum role to run',{choices:[['analyst','Analyst'],['admin','Administrator']],value:row?.run_role||'analyst'});
      field(f.node,'steps','Plan steps (JSON)',{multiline:true,value:JSON.stringify(row?.spec.steps||[{kind:'collect',config:{collection_id:`${state.workspace}-general`}},{kind:'publish',config:{}}],null,2)});f.done();
    }
    p.append(button('New report plan',()=>edit(),true));
  },
  async jobs() {
    const [jobs,artifacts,collections]=await Promise.all([api('/api/jobs'),api('/api/artifacts'),api('/api/collections')]);
    const p=panel('Background jobs');p.append(button('Refresh',render,true));
    table(p,['Job','Type','State','Action'],jobs.map(j=>{const actions=el('div',undefined,'row');actions.append(button('Details',async()=>showJSON(p,await api(`/api/jobs/${j.id}`)),true));if(j.state==='queued')actions.append(button('Cancel',async()=>{await api(`/api/jobs/${j.id}/cancel`,'POST');await render();},true));return[j.id,j.kind,j.state,actions];}));
    const a=panel('Published reports');table(a,['File','Created','Action'],artifacts.map(a=>[a.filename,new Date(a.created_at*1000).toLocaleString(),button('Read report',async()=>showJSON(content,await api(`/api/artifacts/${a.id}`)),true)]));
    const exp=panel('Export a collection');const f=form(exp,'Queue export',async(data)=>{await api('/api/exports','POST',{collection_id:data.collection_id,format:data.format,delay_seconds:Number(data.delay)});await render();});
    field(f.node,'collection_id','Collection',{choices:collections.map(c=>[c.id,c.name])});field(f.node,'format','Format',{choices:[['markdown','Markdown'],['json','JSON']]});field(f.node,'delay','Schedule delay (seconds)',{type:'number',value:0});f.done();
  },
  async team() {
    const [members,audit]=await Promise.all([api('/api/members'),api('/api/audit')]);const p=panel('Workspace members');
    table(p,['Name','Email','Role'],members.map(m=>{const select=field(el('div'),'role','Role',{choices:[['viewer','Viewer'],['analyst','Analyst'],['admin','Administrator']],value:m.role});select.onchange=async()=>{try{await api(`/api/members/${m.id}`,'PATCH',{role:select.value});notice('Role updated.');}catch(e){notice(e.message);}};return[m.display_name,m.email,select];}));
    const log=panel('Audit trail');table(log,['Time','Actor','Action','Resource'],audit.reverse().map(e=>[new Date(e.created_at*1000).toLocaleString(),e.actor_id,e.action,e.resource_id]));
  }
};
$('#login').onsubmit=async(event)=>{event.preventDefault();try{const data=Object.fromEntries(new FormData(event.target));const result=await api('/api/auth/login','POST',data);state.token=result.access_token;sessionStorage.setItem('meridian-token',state.token);await initialize();}catch(e){notice(e.message);}};
$('#logout').onclick=async()=>{try{await api('/api/auth/logout','POST');}finally{sessionStorage.removeItem('meridian-token');location.reload();}};
$('#workspace').onchange=async(event)=>{state.workspace=event.target.value;sessionStorage.setItem('meridian-workspace',state.workspace);try{await render();}catch(e){notice(e.message);}};
document.querySelectorAll('nav button').forEach(node=>node.onclick=async()=>{if(!state.me)return;state.page=node.dataset.page;try{await render();}catch(e){notice(e.message);}});
initialize();
