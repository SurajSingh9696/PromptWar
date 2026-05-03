/**
 * firebase-init.js — VoteWise India
 * Initialized Firebase App, Auth (anonymous), Analytics, Performance.
 * Firebase Hosting auto-injects config via /__/firebase/init.json
 */

import { initializeApp }     from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js';
import { getAuth, signInAnonymously, onAuthStateChanged }
                             from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js';
import { getAnalytics, logEvent, setUserId }
                             from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-analytics.js';
import { getPerformance, trace }
                             from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-performance.js';
import { getRemoteConfig, fetchAndActivate }
                             from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-remote-config.js';
import { initializeAppCheck, ReCaptchaEnterpriseProvider, getToken } 
                             from 'https://www.gstatic.com/firebasejs/11.6.0/firebase-app-check.js';

// ── Expose a promise that resolves to the ID token (or null) ─────────────────
// app.js awaits window.__vwTokenReady before making API calls.
let _resolveToken;
window.__vwTokenReady = new Promise(resolve => { _resolveToken = resolve; });
window.__vwToken = null;

// ── Load config from Firebase Hosting reserved endpoint ───────────────────────
let firebaseConfig;
try {
  const resp = await fetch('/__/firebase/init.json');
  firebaseConfig = await resp.json();
} catch {
  console.warn('[VoteWise] Firebase Hosting config not found — offline mode.');
  firebaseConfig = null;
  _resolveToken(null);   // unblock app.js immediately in offline mode
}

let analytics, perf, auth, remoteConfig, appCheck;

if (firebaseConfig) {
  const app = initializeApp(firebaseConfig);
  analytics    = getAnalytics(app);
  perf         = getPerformance(app);
  auth         = getAuth(app);
  remoteConfig = getRemoteConfig(app);

  // ── Initialize App Check ──────────────────────────────────────────────────
  try {
    appCheck = initializeAppCheck(app, {
      provider: new ReCaptchaEnterpriseProvider('6LcA49YsAAAAAKWpKbcoe31z5j6-nHCZfMVdyHf7'),
      isTokenAutoRefreshEnabled: true
    });
    console.log('[VoteWise] App Check initialized.');
  } catch (e) {
    console.warn('[VoteWise] App Check failed to initialize:', e.message);
  }

  // ── Remote Config defaults ────────────────────────────────────────────────
  remoteConfig.defaultConfig = {
    active_model: 'gemini-2.5-flash-lite-preview-06-17',
    enable_cache: true,
  };
  remoteConfig.settings.minimumFetchIntervalMillis = 3_600_000;

  try { await fetchAndActivate(remoteConfig); }
  catch (e) { console.warn('[VoteWise] Remote Config fallback:', e.message); }

  // ── Anonymous Sign-In + token resolution ─────────────────────────────────
  onAuthStateChanged(auth, async (user) => {
    if (user) {
      const token = await user.getIdToken();
      window.__vwToken = token;
      setUserId(analytics, user.uid);
      _resolveToken(token);    // ← unblocks app.js sendMessage()

      // Refresh token every 55 min (tokens expire at 60 min)
      setInterval(async () => {
        window.__vwToken = await user.getIdToken(true);
      }, 55 * 60 * 1000);
    }
  });

  try { await signInAnonymously(auth); }
  catch (e) {
    console.warn('[VoteWise] Anonymous sign-in failed:', e.message);
    _resolveToken(null);   // unblock even on auth failure — function will handle 401
  }

  // ── Startup performance trace ─────────────────────────────────────────────
  const startupTrace = trace(perf, 'app_startup');
  startupTrace.start();
  window.addEventListener('load', () => startupTrace.stop());
}

// ── Expose Firebase helpers to app.js ─────────────────────────────────────────
window.__firebase = { 
  analytics, perf, trace, logEvent, appCheck,
  getAppCheckToken: async () => {
    if (!appCheck) return null;
    try {
      const result = await getToken(appCheck, false);
      return result.token;
    } catch (e) {
      console.warn("AppCheck getToken failed:", e);
      return null;
    }
  }
};
