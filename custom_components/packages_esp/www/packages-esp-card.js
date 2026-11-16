/* Packages España: no libraries, no remote assets, no email HTML interpolation. */
const WORDS = {
  en: {title:"Deliveries", today:"Today", tomorrow:"Tomorrow", pickups_ready:"Ready to collect", upcoming:"Upcoming", attention:"Needs attention", unknown:"Date unknown", empty:"Nothing here", stale:"Information may be out of date", loading:"Importing email history…", details:"Details", delivered:"Mark delivered", collected:"Mark collected", ignore:"Ignore", clear:"Clear correction", date:"Correct date", snooze:"Snooze 24h", email:"Source email", tracking:"Track parcel", close:"Close", expected:"Expected", scheduled:"Scheduled", deadline:"Collect by", evidence:"Latest evidence", refresh:"Refresh", error:"Unable to load deliveries"},
  es: {title:"Entregas", today:"Hoy", tomorrow:"Mañana", pickups_ready:"Listos para recoger", upcoming:"Próximamente", attention:"Requieren atención", unknown:"Fecha desconocida", empty:"Nada pendiente", stale:"La información puede estar desactualizada", loading:"Importando correos…", details:"Detalles", delivered:"Marcar entregado", collected:"Marcar recogido", ignore:"Ignorar", clear:"Borrar corrección", date:"Corregir fecha", snooze:"Silenciar 24 h", email:"Correo de origen", tracking:"Seguir envío", close:"Cerrar", expected:"Previsto", scheduled:"Programado", deadline:"Recoger antes del", evidence:"Última actualización", refresh:"Actualizar", error:"No se pueden cargar las entregas"}
};
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
const STATUS = {
  en: {ordered:"Ordered",preparing:"Preparing",in_transit:"In transit",out_for_delivery:"Out for delivery",ready_for_pickup:"Ready for pickup",delivered:"Delivered",collected:"Collected",delivery_attempted:"Delivery attempted",delayed:"Delayed",cancelled:"Cancelled",returning:"Returning",returned:"Returned",unknown:"Status unknown",high:"High confidence",medium:"Estimated",low:"Uncertain"},
  es: {ordered:"Pedido confirmado",preparing:"En preparación",in_transit:"En tránsito",out_for_delivery:"En reparto",ready_for_pickup:"Listo para recoger",delivered:"Entregado",collected:"Recogido",delivery_attempted:"Intento de entrega",delayed:"Retrasado",cancelled:"Cancelado",returning:"En devolución",returned:"Devuelto",unknown:"Estado desconocido",high:"Confianza alta",medium:"Estimado",low:"Sin confirmar"}
};
class PackagesEspCard extends HTMLElement {
  setConfig(config) { this.config = {...config}; this.lastFetch = 0; }
  set hass(value) {
    this._hass = value;
    if (!this.busy && Date.now() - (this.lastFetch || 0) > 30000) this.load();
  }
  getCardSize() { return 6; }
  connectedCallback() { this.timer = setInterval(() => this.load(), 60000); }
  disconnectedCallback() { clearInterval(this.timer); }
  get words() { return WORDS[this.config?.language || this._hass?.language?.slice(0,2)] || WORDS.en; }
  label(value) { return (STATUS[this.config?.language || this._hass?.language?.slice(0,2)] || STATUS.en)[value] || value.replaceAll('_',' '); }
  async request(service, data = {}, response = true) {
    const request = {type:"call_service", domain:"packages_esp", service,
      service_data:{...(this.config.entry_id ? {entry_id:this.config.entry_id} : {}), ...data}};
    if (response) request.return_response = true;
    const result = await this._hass.callWS(request);
    return result?.response;
  }
  async load() {
    if (!this._hass || !this.config || this.busy) return;
    this.busy = true;
    try { this.data = await this.request("get_deliveries"); this.error = null; }
    catch { this.error = this.words.error; }
    finally { this.busy = false; this.lastFetch = Date.now(); this.render(); }
  }
  button(parent, text, action) {
    const b = element("button", text, parent); b.type = "button";
    b.addEventListener("click", async () => { b.disabled = true; try { await action(); } catch { this.error = this.words.error; this.render(); } finally { b.disabled = false; } });
    return b;
  }
  link(parent, text, value) {
    try { const url = new URL(value); if (url.protocol !== "https:") return;
      const a = element("a", text, parent); a.href=url.href; a.target="_blank"; a.rel="noopener noreferrer";
    } catch { /* Invalid email links are not rendered. */ }
  }
  async act(action, id, values={}) { await this.request(action, {parcel_id:id, ...values}, false); this.selected=null; await this.load(); }
  render() {
    const w=this.words;
    this.replaceChildren();
    const style=element("style", undefined, this);
    style.textContent="packages-esp-card ha-card{display:block;padding:20px} packages-esp-card h2{margin:0 0 16px} packages-esp-card h3{font-size:16px;margin:20px 0 8px} packages-esp-card article{padding:12px 0;border-bottom:1px solid var(--divider-color,#ddd)} packages-esp-card p{margin:5px 0;line-height:1.5} packages-esp-card small{color:var(--secondary-text-color,#666)} packages-esp-card button{cursor:pointer;padding:8px 12px;margin:6px 8px 0 0;border:1px solid var(--divider-color,#aaa);border-radius:12px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#222)} packages-esp-card a{display:inline-block;margin:8px 16px 8px 0;color:var(--primary-color,#03a9f4)} packages-esp-card .notice{padding:12px;background:var(--secondary-background-color,#eee);border-radius:8px} packages-esp-card input{padding:8px} packages-esp-card section[role=dialog]{border:2px solid var(--primary-color,#03a9f4);padding:16px;margin-top:16px;border-radius:12px}";
    const card=element("ha-card",undefined,this);
    element("h2",this.config.title || w.title,card);
    if(this.error) element("p",this.error,card).className="notice";
    if(!this.data) return;
    if(this.data.stale) element("p",w.stale,card).className="notice";
    if(this.data.initial_import) element("p",w.loading,card).className="notice";
    for(const key of ["today","tomorrow","pickups_ready","upcoming","attention","unknown"]) {
      const rows=this.data.groups[key] || [];
      if(!rows.length && !["today","tomorrow"].includes(key)) continue;
      const section=element("section",undefined,card); element("h3",`${w[key]} · ${rows.length}`,section);
      if(!rows.length) element("small",w.empty,section);
      for(const p of rows) {
        const row=element("article",undefined,section);
        element("strong",p.retailer,row);
        if(p.description && !this.config.hide_items) element("p",p.description,row);
        const expected=p.expected_date ? `${p.scheduled?w.scheduled:w.expected}: ${p.expected_date}${p.expected_end?' – '+p.expected_end:''} ${(p.window||[]).join('–')}` : '';
        element("p",[expected,p.carrier,this.label(p.status)].filter(Boolean).join(' · '),row);
        if(p.pickup_deadline) element("p",`${w.deadline}: ${p.pickup_deadline}`,row);
        element("small",this.label(p.confidence),row);
        this.button(row,w.details,async()=>{this.selected=await this.request("get_deliveries",{parcel_id:p.id});this.render();});
      }
    }
    if(this.selected) {
      const {parcel:p,history}=this.selected;
      const detail=element("section",undefined,card); detail.setAttribute("role","dialog"); detail.setAttribute("aria-label",w.details);
      element("h3",p.retailer,detail);
      if(p.pickup_location) element("p",p.pickup_location,detail);
      if(p.review_reason) element("p",p.review_reason.replaceAll('_',' '),detail);
      element("p",`${w.evidence}: ${history.at(-1)?.source || ''} · ${p.updated_at}`,detail);
      this.link(detail,w.email,p.source_url);this.link(detail,w.tracking,p.tracking_url);
      for(const [action,label] of [["mark_delivered","delivered"],["mark_collected","collected"],["ignore","ignore"],["clear_override","clear"]]) this.button(detail,w[label],()=>this.act(action,p.id));
      this.button(detail,w.snooze,()=>this.act("snooze",p.id,{until:new Date(Date.now()+86400000).toISOString()}));
      const input=element("input",undefined,detail);input.type="date";input.setAttribute("aria-label",w.date);input.value=p.expected_date||'';
      this.button(detail,w.date,()=>input.value?this.act("set_expected_date",p.id,{date:input.value}):Promise.resolve());
      this.button(detail,w.close,()=>{this.selected=null;this.render();});
    }
    this.button(card,w.refresh,async()=>{await this.request("refresh",{},false);await this.load();});
  }
}
if(!customElements.get("packages-esp-card"))customElements.define("packages-esp-card",PackagesEspCard);
window.customCards=window.customCards||[];
window.customCards.push({type:"packages-esp-card",name:"Packages España",description:"Deliveries, pickup deadlines and exceptions"});
