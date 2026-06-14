const authRaw = localStorage.getItem("voice_draw_auth");
if (authRaw) {
  try {
    const auth = JSON.parse(authRaw);
    fetch("/api/me", { headers: { Authorization: `Bearer ${auth.token}` } })
      .then(async (response) => {
        if (!response.ok) throw new Error("expired");
        const user = await response.json();
        const actions = document.querySelector(".marketing-actions");
        if (!actions) return;
        const target = user.role === "admin" ? "/admin/dashboard" : "/workspace";
        actions.innerHTML = `<span class="welcome-user">你好，${user.username}</span><a class="button button-primary" href="${target}">进入${user.role === "admin" ? "后台" : "工作台"}</a>`;
      })
      .catch(() => localStorage.removeItem("voice_draw_auth"));
  } catch (_) {
    localStorage.removeItem("voice_draw_auth");
  }
}
