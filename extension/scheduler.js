'use strict';
const LPScheduler = {
 canSend(turn, poll) {
  return turn?.status === 'ready' && Number(poll.serverTime || Date.now()/1000) >= Math.max(Number(turn.due || 0), Number(poll.nextSendAt || 0));
 },
 nextContact(rows, visited, now, blocked = new Set()) {
  return rows.filter(r => !blocked.has(r.contact) && now-(visited.get(r.contact)||0)>30000)
   .sort((a,b)=>(visited.get(a.contact)||0)-(visited.get(b.contact)||0) || Number(b.unread)-Number(a.unread))[0];
 }
};
if(typeof module !== 'undefined') module.exports=LPScheduler;
