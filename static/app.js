'use strict';
/* ===== CONFIG ===== */
/** @type {string} Session-scoped client cache version key */
const CACHE_VERSION = 'v3';
/** @type {number} Client-side cache TTL in milliseconds (10 minutes) */
const CACHE_TTL_MS = 6e5;
/** @type {number} Debounce delay for form submit in milliseconds */
const DEBOUNCE_MS = 300;
/** @type {number} Maximum message length enforced client-side (mirrors backend) */
const MAX_MESSAGE_LEN = 500;

/* ===== ELEMENTS ===== */
const $=id=>document.getElementById(id);
const chatLog=$("chat-log"),chatForm=$("chat-form"),userInput=$("user-input"),
typingIndicator=$("typing-indicator"),followupsContainer=$("followups-container"),
themeToggle=$("theme-toggle"),sidebarOpen=$("sidebar-open"),sidebarClose=$("sidebar-close"),
sidebar=$("sidebar"),stateSelect=$("state-select"),ageinput=$("age-input"),
citizenCheck=$("citizen-check"),checkBtn=$("check-eligibility-btn"),
eligibilityResult=$("eligibility-result"),stateBadge=$("state-badge"),
langSelect=$("lang-select");

/* ===== STATE ===== */
let conversationContext={},sendDebounceTimer=null,isSending=false,currentLang="en";

/* ===== I18N — compact UI strings for top 6 languages ===== */
const UI_STRINGS={
  hi:{selectState:"अपना राज्य चुनें",quickEligibility:"पात्रता जाँच",citizenLabel:"मैं भारतीय नागरिक हूँ",checkEligibility:"जाँचें",quickTopics:"त्वरित विषय",eciResources:"ECI संसाधन",disclaimer:"⚠️ डेटा ECI से। eci.gov.in पर सत्यापित करें।",poweredBy:"ECI डेटा द्वारा संचालित",inputPlaceholder:"मतदाता पंजीकरण, EPIC, चुनाव तिथियों के बारे में पूछें…",agePlaceholder:"आपकी उम्र (18+)",welcomeTitle:"नमस्ते! मैं VoteWise India हूँ — भारतीय चुनावों के लिए आपका गैर-पक्षपाती गाइड।",welcomeHelp:"मैं इसमें मदद कर सकता हूँ:",welcomeAction:"व्यक्तिगत जानकारी के लिए साइडबार से अपना राज्य चुनें!",w1:"✅ मतदाता पंजीकरण (फॉर्म 6) और EPIC",w2:"✅ राज्यवार चुनाव कार्यक्रम",w3:"✅ मतदाता सूची खोज और मतदान केंद्र",w4:"✅ EVM/VVPAT, आदर्श आचार संहिता",w5:"✅ मतदान केंद्र पर स्वीकृत वैकल्पिक ID"},
  bn:{selectState:"আপনার রাজ্য নির্বাচন করুন",quickEligibility:"যোগ্যতা যাচাই",citizenLabel:"আমি ভারতীয় নাগরিক",checkEligibility:"যাচাই করুন",quickTopics:"দ্রুত বিষয়",eciResources:"ECI সম্পদ",disclaimer:"⚠️ তথ্য ECI থেকে। eci.gov.in-এ যাচাই করুন।",poweredBy:"ECI ডেটা দ্বারা চালিত",inputPlaceholder:"ভোটার নিবন্ধন, EPIC সম্পর্কে জিজ্ঞাসা করুন…",agePlaceholder:"আপনার বয়স (18+)",welcomeTitle:"নমস্কার! আমি VoteWise India — নির্বাচনের জন্য আপনার নিরপেক্ষ গাইড।",welcomeHelp:"আমি সাহায্য করতে পারি:",welcomeAction:"ব্যক্তিগত তথ্যের জন্য সাইডবার থেকে রাজ্য নির্বাচন করুন!",w1:"✅ ভোটার নিবন্ধন (ফর্ম 6) ও EPIC",w2:"✅ রাজ্যভিত্তিক নির্বাচনের সময়সূচি",w3:"✅ ভোটার তালিকা অনুসন্ধান",w4:"✅ EVM/VVPAT, আদর্শ আচরণবিধি",w5:"✅ বিকল্প পরিচয়পত্র"},
  ta:{selectState:"உங்கள் மாநிலத்தைத் தேர்ந்தெடுக்கவும்",quickEligibility:"தகுதி சோதனை",citizenLabel:"நான் இந்திய குடிமகன்",checkEligibility:"சரிபார்",quickTopics:"விரைவு தலைப்புகள்",eciResources:"ECI ஆதாரங்கள்",disclaimer:"⚠️ ECI தரவு. eci.gov.in-ல் சரிபார்க்கவும்.",poweredBy:"ECI தரவால் இயக்கப்படுகிறது",inputPlaceholder:"வாக்காளர் பதிவு பற்றி கேளுங்கள்…",agePlaceholder:"உங்கள் வயது (18+)"},
  te:{selectState:"మీ రాష్ట్రాన్ని ఎంచుకోండి",quickEligibility:"అర్హత తనిఖీ",citizenLabel:"నేను భారత పౌరుడిని",checkEligibility:"తనిఖీ",quickTopics:"త్వరిత అంశాలు",eciResources:"ECI వనరులు",disclaimer:"⚠️ ECI డేటా. eci.gov.in లో ధృవీకరించండి.",poweredBy:"ECI డేటా ద్వారా",inputPlaceholder:"ఓటరు నమోదు గురించి అడగండి…",agePlaceholder:"మీ వయస్సు (18+)"},
  mr:{selectState:"तुमचे राज्य निवडा",quickEligibility:"पात्रता तपासा",citizenLabel:"मी भारतीय नागरिक आहे",checkEligibility:"तपासा",quickTopics:"जलद विषय",eciResources:"ECI संसाधने",disclaimer:"⚠️ डेटा ECI कडून. eci.gov.in वर खात्री करा.",poweredBy:"ECI डेटा द्वारे",inputPlaceholder:"मतदार नोंदणीबद्दल विचारा…",agePlaceholder:"तुमचे वय (18+)"},
  gu:{selectState:"તમારું રાજ્ય પસંદ કરો",quickEligibility:"પાત્રતા ચકાસો",citizenLabel:"હું ભારતીય નાગરિક છું",checkEligibility:"ચકાસો",quickTopics:"ઝડપી વિષયો",eciResources:"ECI સંસાધનો",disclaimer:"⚠️ ECI ડેટા. eci.gov.in પર ચકાસો.",poweredBy:"ECI ડેટા દ્વારા",inputPlaceholder:"મતદાર નોંધણી વિશે પૂછો…",agePlaceholder:"તમારી ઉંમર (18+)"},
  kn:{selectState:"ನಿಮ್ಮ ರಾಜ್ಯವನ್ನು ಆಯ್ಕೆಮಾಡಿ",quickEligibility:"ಅರ್ಹತೆ ಪರಿಶೀಲನೆ",citizenLabel:"ನಾನು ಭಾರತೀಯ ಪ್ರಜೆ",checkEligibility:"ಪರಿಶೀಲಿಸಿ",quickTopics:"ತ್ವರಿತ ವಿಷಯಗಳು",eciResources:"ECI ಸಂಪನ್ಮೂಲಗಳು",poweredBy:"ECI ಡೇಟಾ ಮೂಲಕ",inputPlaceholder:"ಮತದಾರ ನೋಂದಣಿ ಬಗ್ಗೆ ಕೇಳಿ…",agePlaceholder:"ನಿಮ್ಮ ವಯಸ್ಸು (18+)"},
  ml:{selectState:"നിങ്ങളുടെ സംസ്ഥാനം തിരഞ്ഞെടുക്കുക",quickEligibility:"യോഗ്യത പരിശോധന",citizenLabel:"ഞാൻ ഇന്ത്യൻ പൗരൻ",checkEligibility:"പരിശോധിക്കുക",quickTopics:"ദ്രുത വിഷയങ്ങൾ",eciResources:"ECI വിഭവങ്ങൾ",poweredBy:"ECI ഡാറ്റ വഴി",inputPlaceholder:"വോട്ടർ രജിസ്ട്രേഷൻ കുറിച്ച് ചോദിക്കൂ…",agePlaceholder:"നിങ്ങളുടെ പ്രായം (18+)"},
  pa:{selectState:"ਆਪਣਾ ਰਾਜ ਚੁਣੋ",quickEligibility:"ਯੋਗਤਾ ਜਾਂਚ",citizenLabel:"ਮੈਂ ਭਾਰਤੀ ਨਾਗਰਿਕ ਹਾਂ",checkEligibility:"ਜਾਂਚੋ",quickTopics:"ਤੇਜ਼ ਵਿਸ਼ੇ",eciResources:"ECI ਸਰੋਤ",poweredBy:"ECI ਡੇਟਾ ਦੁਆਰਾ",inputPlaceholder:"ਵੋਟਰ ਰਜਿਸਟ੍ਰੇਸ਼ਨ ਬਾਰੇ ਪੁੱਛੋ…",agePlaceholder:"ਤੁਹਾਡੀ ਉਮਰ (18+)"},
  or:{selectState:"ଆପଣଙ୍କ ରାଜ୍ୟ ବାଛନ୍ତୁ",quickEligibility:"ଯୋଗ୍ୟତା ଯାଞ୍ଚ",citizenLabel:"ମୁଁ ଭାରତୀୟ ନାଗରିକ",checkEligibility:"ଯାଞ୍ଚ କରନ୍ତୁ",quickTopics:"ଦ୍ରୁତ ବିଷୟ",eciResources:"ECI ସମ୍ବଳ",poweredBy:"ECI ତଥ୍ୟ ଦ୍ୱାରା",inputPlaceholder:"ଭୋଟର ପଞ୍ଜୀକରଣ ବିଷୟରେ ପଚାରନ୍ତୁ…",agePlaceholder:"ଆପଣଙ୍କ ବୟସ (18+)"}
};

/* ===== LANGUAGE NAMES (for Gemini prompt) ===== */
const LANG_NAMES={en:"English",hi:"Hindi",bn:"Bengali",te:"Telugu",mr:"Marathi",ta:"Tamil",ur:"Urdu",gu:"Gujarati",kn:"Kannada",ml:"Malayalam",or:"Odia",pa:"Punjabi",as:"Assamese",mai:"Maithili",sa:"Sanskrit",ne:"Nepali",sd:"Sindhi",ks:"Kashmiri",doi:"Dogri",kok:"Konkani",mni:"Manipuri",sat:"Santali",bo:"Bodo"};

/**
 * Applies a UI language to all i18n-annotated DOM elements.
 * Also updates the <html lang> attribute and persists the choice.
 * @param {string} lang - BCP 47 language code (e.g. 'hi', 'bn').
 */
function applyLang(lang){
  currentLang=lang;
  // Update the HTML lang attribute for screen readers
  document.documentElement.lang = lang;
  const s=UI_STRINGS[lang]||{};
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key=el.dataset.i18n;
    if(s[key]) el.innerHTML=s[key];
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>{
    const key=el.dataset.i18nPh;
    if(s[key]) el.placeholder=s[key];
  });
  conversationContext.language=LANG_NAMES[lang]||'English';
  localStorage.setItem('vw-lang',lang);
}

/* ===== THEME ===== */
const setTheme=t=>{document.documentElement.setAttribute("data-theme",t);themeToggle.textContent=t==="dark"?"☀️":"🌙";localStorage.setItem("vw-theme",t)};
themeToggle.addEventListener("click",()=>setTheme(document.documentElement.getAttribute("data-theme")==="dark"?"light":"dark"));
setTheme(localStorage.getItem("vw-theme")||"dark");

/* ===== SIDEBAR ===== */
sidebarOpen?.addEventListener("click",()=>sidebar.classList.add("open"));
sidebarClose?.addEventListener("click",()=>sidebar.classList.remove("open"));

/* ===== STATE NAMES ===== */
const STATE_NAMES={DL:"Delhi",BR:"Bihar",WB:"West Bengal",TN:"Tamil Nadu",KL:"Kerala",AS:"Assam",UP:"Uttar Pradesh",MH:"Maharashtra",GJ:"Gujarat",RJ:"Rajasthan",KA:"Karnataka",MP:"Madhya Pradesh",PB:"Punjab"};

/* ===== STATE SELECTOR ===== */
stateSelect.addEventListener("change",()=>{
  const s=stateSelect.value;
  if(s){conversationContext.state=s;const n=STATE_NAMES[s]||s;stateBadge.textContent=`${n} — ECI Data`;appendBot(`📍 Got it! I'll use **${n}** for state-specific info.`,"local")}
  else{delete conversationContext.state;stateBadge.textContent="Powered by ECI Data"}
});

/* ===== TOPIC / NAV CHIPS ===== */
document.querySelectorAll(".topic-chip,.nav-chip").forEach(c=>c.addEventListener("click",()=>{
  sidebar.classList.remove("open");
  sendMessage(c.dataset.msg);
}));

/* ===== LANGUAGE SELECTOR ===== */
langSelect.addEventListener("change",()=>applyLang(langSelect.value));

/* ===== ELIGIBILITY ===== */
checkBtn.addEventListener("click",async()=>{
  const age=parseInt(ageinput.value,10),citizen=citizenCheck.checked,state=stateSelect.value||"DL";
  if(isNaN(age)||age<0||age>120){eligibilityResult.textContent="⚠️ Enter a valid age (0–120).";eligibilityResult.className="ineligible";eligibilityResult.classList.remove("hidden");return}
  try{
    // Wait for Firebase anonymous auth to complete before calling the API
    if(window.__vwTokenReady) await window.__vwTokenReady;
    const headers={"Content-Type":"application/json"};
    if(window.__vwToken) headers["Authorization"]="Bearer "+window.__vwToken;
    if(window.__firebase?.getAppCheckToken){
      const acToken = await window.__firebase.getAppCheckToken();
      if(acToken) headers["X-Firebase-AppCheck"] = acToken;
    }
    const r=await fetch(`/eligibility?age=${age}&citizen=${citizen}&state=${state}`,{headers});const d=await r.json();eligibilityResult.classList.remove("hidden");
    if(d.eligible){eligibilityResult.textContent="✅ You appear eligible to vote!";eligibilityResult.className="eligible"}
    else{eligibilityResult.textContent=`❌ ${d.reasons[0]}`;eligibilityResult.className="ineligible"}
  }catch(e){
    eligibilityResult.className="ineligible";
    eligibilityResult.classList.remove("hidden");
    if(!navigator.onLine || e.message?.includes("Failed to fetch") || e.message?.includes("NetworkError")){
      eligibilityResult.textContent="📶 Please check your internet connection.";
    }else{
      eligibilityResult.textContent="⚠️ Could not check.";
    }
  }
});

/**
 * Returns the session-storage cache key for a message.
 * @param {string} m - The user message string.
 * @returns {string} Cache key.
 */
const cacheKey=m=>`${CACHE_VERSION}:${m.trim().toLowerCase()}`;

/**
 * Reads a cached API response from sessionStorage.
 * @param {string} m - The user message string.
 * @returns {Object|null} Cached data object or null on miss/expiry.
 */
const getCache=m=>{try{const r=sessionStorage.getItem(cacheKey(m));if(!r)return null;const{data,ts}=JSON.parse(r);if(Date.now()-ts>CACHE_TTL_MS){sessionStorage.removeItem(cacheKey(m));return null}return data}catch{return null}};

/**
 * Writes an API response to sessionStorage cache.
 * @param {string} m - The user message string.
 * @param {Object} d - The response data to cache.
 */
const setCache=(m,d)=>{try{sessionStorage.setItem(cacheKey(m),JSON.stringify({data:d,ts:Date.now()}))}catch{}};

/* ===== UI HELPERS ===== */
/** Scrolls the chat log to the latest message. */
const scrollBottom=()=>chatLog.scrollTo({top:chatLog.scrollHeight,behavior:'smooth'});

/**
 * Escapes HTML special characters to prevent XSS in user-supplied text.
 * @param {string} s - Raw string to escape.
 * @returns {string} HTML-safe string.
 */
const escapeHtml=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/**
 * Appends a user message bubble to the chat log.
 * @param {string} t - The user message text.
 */
function appendUser(t){const r=document.createElement('div');r.className='msg-row user';r.setAttribute('role','listitem');r.innerHTML=`<div class="bubble user-bubble">${escapeHtml(t)}</div>`;chatLog.appendChild(r);scrollBottom()}

/**
 * Appends a bot response bubble with source badge and markdown rendering.
 * @param {string} t - The bot reply text (Markdown supported).
 * @param {string} [src='ai'] - Source label: 'local', 'cache', or 'ai'.
 */
function appendBot(t,src='ai'){const r=document.createElement('div');r.className='msg-row bot';r.setAttribute('role','listitem');
  const badge=src==='local'?`<span class="source-badge local">⚡ instant</span>`:`<span class="source-badge ai">🤖 AI</span>`;
  r.innerHTML=`<div class="avatar" aria-hidden="true">🗳️</div><div class="bubble bot-bubble">${marked.parse(t)}<div class="msg-meta">${badge}</div></div>`;
  chatLog.appendChild(r);scrollBottom()}

/**
 * Renders follow-up question chips below the latest bot reply.
 * @param {string[]} chips - Array of follow-up question strings.
 */
function setFollowups(chips){followupsContainer.innerHTML="";chips.slice(0,3).forEach(t=>{const b=document.createElement("button");b.className="followup-chip";b.textContent=t;b.addEventListener("click",()=>sendMessage(t));followupsContainer.appendChild(b)})}

/**
 * Returns contextually relevant follow-up question chips based on the reply.
 * @param {string} r - The bot reply text.
 * @returns {string[]} Array of 3 follow-up questions.
 */
function pick_followups(r){const l=r.toLowerCase();
  if(l.includes('form 6')||l.includes('register'))return['What documents for Form 6?','Can I register online?','Where is my BLO?'];
  if(l.includes('epic')||l.includes('voter id'))return['How to get e-EPIC?','How to correct Voter ID?','Lost my Voter ID?'];
  if(l.includes('evm')||l.includes('vvpat'))return['Is EVM safe?','What is VVPAT?','How to use EVM?'];
  if(l.includes('unable')||l.includes('cannot vote'))return['How to register now?','Name not on list?','What ID do I need?'];
  if(l.includes('lok sabha'))return['What is Vidhan Sabha?','How many Lok Sabha seats?','Next general election?'];
  return['How do I register?','What is EPIC?','Find my polling booth?'];}

/**
 * Sends a user message through the 3-tier response pipeline.
 * Checks client-side cache first, then calls the /chat Cloud Function.
 * Handles Firebase Analytics/Performance tracing and graceful error display.
 * @param {string} text - The message text to send.
 * @returns {Promise<void>}
 */
async function sendMessage(text){
  text=text.trim().slice(0,MAX_MESSAGE_LEN);if(!text||isSending)return;
  appendUser(text);followupsContainer.innerHTML='';userInput.value='';
  const cached=getCache(text);
  if(cached){appendBot(cached.reply,'local');setFollowups(cached.suggested_followups||[]);return}
  isSending=true;
  // Disable send button and signal busy state to assistive technologies
  const sendBtn=document.getElementById('send-btn');
  if(sendBtn){sendBtn.disabled=true;sendBtn.setAttribute('aria-disabled','true');}
  typingIndicator.classList.remove('hidden');scrollBottom();

  // ― Firebase Analytics: log each question ―
  if(window.__firebase?.logEvent && window.__firebase?.analytics){
    try{
      const cat=text.toLowerCase().includes("register")?"registration":
                text.toLowerCase().includes("epic")||text.toLowerCase().includes("voter id")?"epic":
                text.toLowerCase().includes("booth")?"booth":"general";
      window.__firebase.logEvent(window.__firebase.analytics,"question_asked",{
        category:cat,
        state:conversationContext.state||"none",
        language:conversationContext.language||"English"
      });
    }catch(_){}
  }

  // ― Firebase Performance: trace per chat request ―
  let perfTrace=null;
  if(window.__firebase?.trace && window.__firebase?.perf){
    try{perfTrace=window.__firebase.trace(window.__firebase.perf,"chat_request");perfTrace.start();}catch(_){}
  }

  try{
    // Wait for Firebase Auth token before calling protected API
    if(window.__vwTokenReady) await window.__vwTokenReady;
    const headers={"Content-Type":"application/json"};
    if(window.__vwToken) headers["Authorization"]="Bearer "+window.__vwToken;
    if(window.__firebase?.getAppCheckToken){
      const acToken = await window.__firebase.getAppCheckToken();
      if(acToken) headers["X-Firebase-AppCheck"] = acToken;
    }
    const res=await fetch("/chat",{method:"POST",headers,body:JSON.stringify({message:text,context:conversationContext})});
    typingIndicator.classList.add("hidden");
    if(!res.ok){
      const errBody=await res.text();
      console.error("[VoteWise] API error:",res.status,errBody);
      throw new Error(`HTTP ${res.status}: ${errBody}`);
    }
    const data=await res.json();
    appendBot(data.reply,data.source||"ai");
    setFollowups(data.suggested_followups||pick_followups(data.reply));
    setCache(text,data);
  }catch(e){
    typingIndicator.classList.add("hidden");
    if(!navigator.onLine || e.message.includes("Failed to fetch") || e.message.includes("NetworkError")){
      appendBot("📶 Please check your internet connection and try again.","local");
    }else{
      appendBot("⚠️ Something went wrong. Visit [eci.gov.in](https://eci.gov.in) or call **1950**.","local");
    }
    console.error(e);
  }
  finally{
    isSending=false;
    // Re-enable send button
    if(sendBtn){sendBtn.disabled=false;sendBtn.setAttribute('aria-disabled','false');}
    try{perfTrace?.stop();}catch(_){}
  }
}

/* ===== FORM SUBMIT ===== */
chatForm.addEventListener("submit",e=>{e.preventDefault();clearTimeout(sendDebounceTimer);sendDebounceTimer=setTimeout(()=>sendMessage(userInput.value),DEBOUNCE_MS)});
userInput.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();chatForm.dispatchEvent(new Event("submit"))}});

/* ===== RESTORE STATE ===== */
const savedState=sessionStorage.getItem("vw-india-state");
if(savedState){stateSelect.value=savedState;conversationContext.state=savedState;stateBadge.textContent=`${STATE_NAMES[savedState]||savedState} — ECI Data`}
stateSelect.addEventListener("change",()=>sessionStorage.setItem("vw-india-state",stateSelect.value));

/* ===== RESTORE LANGUAGE ===== */
const savedLang=localStorage.getItem("vw-lang")||"en";
langSelect.value=savedLang;
applyLang(savedLang);
