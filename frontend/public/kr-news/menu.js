(function(){
  var btn=document.getElementById('menu-toggle');
  var drw=document.getElementById('mobile-drawer');
  var bd=document.getElementById('drawer-backdrop');
  if(!btn||!drw||!bd)return;
  function toggle(open){
    var willOpen=(typeof open==='boolean')?open:!drw.classList.contains('open');
    drw.classList.toggle('open',willOpen);
    bd.classList.toggle('open',willOpen);
    btn.classList.toggle('open',willOpen);
    btn.setAttribute('aria-expanded',willOpen);
  }
  btn.addEventListener('click',function(){toggle();});
  bd.addEventListener('click',function(){toggle(false);});
  drw.querySelectorAll('a').forEach(function(a){a.addEventListener('click',function(){toggle(false);});});
})();
