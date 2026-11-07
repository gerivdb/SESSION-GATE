function doGet(e) {
  var params = (e && e.parameter) ? e.parameter : {};
  var headers = (e && e.headers) ? e.headers : {};
  var clientKey = headers["X-Forwarded-For"]
    ? headers["X-Forwarded-For"].split(",")[0].trim()
    : (params.token || "anonymous");
  if (!checkRateLimit(clientKey)) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "REJECTED", code: 429,
      message: "[RATE_LIMIT] Limite de 30 requêtes par minute dépassée pour cet identifiant."
    })).setMimeType(ContentService.MimeType.JSON);
  }
  if (!verifySecret(params.secret)) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "REJECTED", code: 403,
      message: "[SECURITY] Secret partagé invalide ou absent."
    })).setMimeType(ContentService.MimeType.JSON);
  }
  var action = params.action || "ping";
  if (action === "ping") {
    return ContentService.createTextOutput(JSON.stringify({
      status: "SUCCESS", strate: "ENV3.pur", wal: "0x243",
      friction: 0.0, message: "Master Proxy Transverse (-b) v2 actif."
    })).setMimeType(ContentService.MimeType.JSON);
  }
  return ContentService.createTextOutput(JSON.stringify({
    status: "ERROR", message: "Action non reconnue."
  })).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    var params = (e && e.parameter) ? e.parameter : {};
    var headers = (e && e.headers) ? e.headers : {};
    var token = params.token;
    if (!token && headers) {
      var authHeader = headers["Authorization"] || headers["authorization"];
      if (authHeader && authHeader.indexOf("Bearer ") === 0) {
        token = authHeader.substring(7).trim();
      }
    }
    var payload = (e && e.postData && e.postData.contents) ? JSON.parse(e.postData.contents) : {};
    var action = payload.action;
    var issuedToken = validateSessionToken(token, payload.user_consent, payload.secret);
    if (!issuedToken) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "REJECTED", code: 403,
        message: "[SECURITY] Authentification échouée : Jeton ou secret invalide."
      })).setMimeType(ContentService.MimeType.JSON);
    }
    if (action === "batch_create_notes") {
      var results = executeBatchNoteCreation(payload.items);
      appendWalLog({
        ts: new Date().toISOString(), action: action,
        processed_count: results.length, wal_id: "0x243"
      });
      var effectiveSessionToken = (typeof issuedToken === "string") ? issuedToken : token;
      return ContentService.createTextOutput(JSON.stringify({
        status: "SUCCESS", rc: 0, wal: "0x243",
        session_token: effectiveSessionToken,
        processed_count: results.length, results: results
      })).setMimeType(ContentService.MimeType.JSON);
    }
    return ContentService.createTextOutput(JSON.stringify({
      status: "INVALID_ACTION", rc: 1
    })).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "EXCEPTION", error: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function validateSessionToken(token, userConsent, secret) {
  var cache = CacheService.getScriptCache();
  if (userConsent === true) {
    if (!verifySecret(secret)) return false;
    var newToken = "WAL-0x243-OAUTH-SESSION-" + Math.floor(Date.now() / 1000) + "-" + Math.random().toString(36).substring(2, 7);
    cache.put(newToken, "valid", 3600);
    return newToken;
  }
  if (token && cache.get(token) === "valid") return true;
  return false;
}

function verifySecret(secretProvided) {
  if (!secretProvided) return false;
  var props = PropertiesService.getScriptProperties();
  var storedHash = props.getProperty("SHARED_SECRET_HASH");
  if (!storedHash) return false;
  var computedHash = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, secretProvided)
    .map(function(byte) { return (byte < 0 ? byte + 256 : byte).toString(16).padStart(2, '0'); })
    .join('');
  return computedHash === storedHash;
}

function checkRateLimit(clientKey) {
  var cache = CacheService.getScriptCache();
  var cacheKey = "RL_" + clientKey;
  var currentCount = parseInt(cache.get(cacheKey) || "0", 10);
  if (currentCount >= 30) return false;
  cache.put(cacheKey, (currentCount + 1).toString(), 60);
  return true;
}

function executeBatchNoteCreation(items) {
  var log = [];
  if (!items || !Array.isArray(items)) return log;
  items.forEach(function(item, idx) {
    var title = item.title || "[CAUSAL] Note Sans Titre";
    var content = item.content || item.text_content || "Contenu vide";
    var file = DriveApp.createFile(title, content, MimeType.PLAIN_TEXT);
    log.push({ index: idx + 1, title: title, file_id: file.getId(), status: "CREATED", url: file.getUrl() });
  });
  return log;
}

function appendWalLog(logEntry) {
  var props = PropertiesService.getScriptProperties();
  var rawLogs = props.getProperty("WAL_LOG") || "";
  var lines = rawLogs ? rawLogs.split("\n") : [];
  lines.push(JSON.stringify(logEntry));
  if (lines.length > 1000) lines = lines.slice(lines.length - 1000);
  props.setProperty("WAL_LOG", lines.join("\n"));
}
