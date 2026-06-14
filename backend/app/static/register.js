const registerForm = document.getElementById("registerForm");
const registerMessage = document.getElementById("registerMessage");
const passwordInput = document.getElementById("registerPassword");
const strengthBar = document.getElementById("strengthBar");
const strengthText = document.getElementById("strengthText");
function setMessage(text, error = false) { registerMessage.textContent = text || ""; registerMessage.classList.toggle("error", !!error); registerMessage.classList.toggle("success", !error && !!text); }
async function postJson(url, payload) { const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || "请求失败"); return data; }
function scorePassword(value) { let score = 0; if (value.length >= 8) score++; if (value.length >= 12) score++; if (/[a-zA-Z]/.test(value) && /\d/.test(value)) score++; if (/[^a-zA-Z0-9]/.test(value)) score++; return score; }
passwordInput?.addEventListener("input", () => { const score = scorePassword(passwordInput.value); const labels = ["尚未输入", "较弱", "一般", "良好", "很强"]; strengthBar.style.width = `${score * 25}%`; strengthBar.dataset.score = String(score); strengthText.textContent = `密码强度：${labels[score]}`; });
document.querySelectorAll(".password-toggle").forEach((button) => button.addEventListener("click", () => { const input = document.getElementById(button.dataset.target); const show = input.type === "password"; input.type = show ? "text" : "password"; button.textContent = show ? "隐藏" : "显示"; }));
registerForm?.addEventListener("submit", async (event) => {
  event.preventDefault(); const formData = new FormData(registerForm); const password = String(formData.get("password") || ""); const confirm = String(formData.get("confirm_password") || "");
  if (password !== confirm) return setMessage("两次输入的密码不一致", true);
  if (scorePassword(password) < 2) return setMessage("密码强度过低，请同时使用字母和数字", true);
  try { setMessage("正在创建账号..."); const data = await postJson("/api/register", { username: String(formData.get("username") || "").trim(), email: String(formData.get("email") || "").trim(), password }); localStorage.setItem("voice_draw_auth", JSON.stringify(data)); setMessage("注册成功，正在进入工作台"); window.location.href = data.redirect_to || "/workspace"; } catch (error) { setMessage(error.message, true); }
});
(async () => { const raw = localStorage.getItem("voice_draw_auth"); if (!raw) return; try { const auth = JSON.parse(raw); const response = await fetch("/api/me", { headers: { Authorization: `Bearer ${auth.token}` } }); if (!response.ok) throw new Error(); const user = await response.json(); window.location.href = user.role === "admin" ? "/admin/dashboard" : "/workspace"; } catch (_) { localStorage.removeItem("voice_draw_auth"); } })();
