const loginForm = document.getElementById("loginForm");
const loginMessage = document.getElementById("loginMessage");
const roleInput = document.getElementById("loginRole");
const roleTabs = [...document.querySelectorAll(".role-tab")];
const portalTitle = document.getElementById("portalTitle");
const portalSubtitle = document.getElementById("portalSubtitle");
const submitText = document.getElementById("submitText");
const userRegisterHint = document.getElementById("userRegisterHint");
const adminSecurityHint = document.getElementById("adminSecurityHint");
const rememberAccount = document.getElementById("rememberAccount");

function setMessage(target, text, error = false) {
  if (!target) return;
  target.textContent = text || "";
  target.classList.toggle("error", !!error);
  target.classList.toggle("success", !error && !!text);
}
function saveAuth(auth) { localStorage.setItem("voice_draw_auth", JSON.stringify(auth)); }
function handleAuthSuccess(data) { saveAuth(data); window.location.href = data.redirect_to || "/workspace"; }
async function postJson(url, payload) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
}
function switchRole(role, updateUrl = true) {
  const normalized = role === "admin" ? "admin" : "user";
  roleInput.value = normalized;
  roleTabs.forEach((tab) => {
    const active = tab.dataset.role === normalized;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  const admin = normalized === "admin";
  portalTitle.textContent = admin ? "登录管理后台" : "登录创作空间";
  portalSubtitle.textContent = admin ? "使用管理员账号进入数据与用户管理中心" : "使用普通用户账号进入语音绘图工作台";
  submitText.textContent = admin ? "进入管理后台" : "进入语音工作台";
  userRegisterHint.classList.toggle("hidden", admin);
  adminSecurityHint.classList.toggle("hidden", !admin);
  document.body.classList.toggle("admin-login-mode", admin);
  setMessage(loginMessage, "");
  if (updateUrl) history.replaceState(null, "", admin ? "/admin/login" : "/login");
}
roleTabs.forEach((tab) => tab.addEventListener("click", () => switchRole(tab.dataset.role)));

document.querySelectorAll(".password-toggle").forEach((button) => button.addEventListener("click", () => {
  const input = document.getElementById(button.dataset.target);
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  button.textContent = show ? "隐藏" : "显示";
}));

document.getElementById("helpLink")?.addEventListener("click", (event) => {
  event.preventDefault();
  setMessage(loginMessage, roleInput.value === "admin" ? "请检查管理员账号配置，或联系项目维护人员重置密码。" : "请确认账号、密码和账号封禁状态。", false);
});

loginForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(loginForm);
  const account = String(formData.get("username") || "").trim();
  const password = String(formData.get("password") || "");
  const role = roleInput.value;
  try {
    setMessage(loginMessage, "正在安全验证账号...");
    const data = await postJson(role === "admin" ? "/api/login/admin" : "/api/login/user", { username: account, password });
    if (rememberAccount.checked) localStorage.setItem("voice_draw_last_account", account);
    else localStorage.removeItem("voice_draw_last_account");
    setMessage(loginMessage, "验证通过，正在进入系统");
    handleAuthSuccess(data);
  } catch (error) { setMessage(loginMessage, error.message, true); }
});

(async () => {
  const account = localStorage.getItem("voice_draw_last_account");
  if (account && loginForm?.elements.username) { loginForm.elements.username.value = account; rememberAccount.checked = true; }
  switchRole(location.pathname.startsWith("/admin/") || new URLSearchParams(location.search).get("role") === "admin" ? "admin" : "user", false);
  const raw = localStorage.getItem("voice_draw_auth");
  if (!raw) return;
  try {
    const auth = JSON.parse(raw);
    const response = await fetch("/api/me", { headers: { Authorization: `Bearer ${auth.token}` } });
    if (!response.ok) throw new Error("expired");
    const user = await response.json();
    window.location.href = user.role === "admin" ? "/admin/dashboard" : "/workspace";
  } catch (_) { localStorage.removeItem("voice_draw_auth"); }
})();
