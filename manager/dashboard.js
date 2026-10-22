(() => {
  const usersBody = document.getElementById("traffic-users");
  const connectionsBody = document.getElementById("traffic-connections");
  if (!usersBody || !connectionsBody) return;

  const byId = (id) => document.getElementById(id);
  const bytes = (value) => {
    let number = Number(value) || 0;
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let unit = 0;
    while (number >= 1024 && unit < units.length - 1) {
      number /= 1024;
      unit += 1;
    }
    return `${number.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
  };
  const speed = (value) => `${bytes(value)}/s`;
  const pair = (values) => `${bytes(values[0])} / ${bytes(values[1])}`;
  const missing = (values) => values && values.length ? values.join(", ") : "未提供";

  function renderRows(body, rows, fields, emptyText) {
    body.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = fields.length;
      td.textContent = emptyText;
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const field of fields) {
        const td = document.createElement("td");
        td.textContent = String(field(row));
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }

  async function refresh() {
    try {
      const response = await fetch("/api/metrics", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      byId("active-users").textContent = data.active_users;
      byId("active-connections").textContent = data.active_connections;
      byId("upload-rate").textContent = speed(data.upload_rate);
      byId("download-rate").textContent = speed(data.download_rate);
      byId("metrics-status").textContent = "每 2 秒刷新。上传、下载按客户端方向计算，包含 WebSocket／VMess 协议开销。";
      renderRows(usersBody, data.users, [
        (row) => row.name,
        (row) => row.connections,
        (row) => missing(row.ips),
        (row) => missing(row.locations),
        (row) => speed(row.upload_rate),
        (row) => speed(row.download_rate),
        (row) => pair(row.today),
        (row) => pair(row.days7),
        (row) => pair(row.days30),
      ], "暂无用户");
      renderRows(connectionsBody, data.connections, [
        (row) => row.user,
        (row) => row.ip || "未提供",
        (row) => row.location || "未提供",
        (row) => `${row.seconds} 秒`,
        (row) => speed(row.upload_rate),
        (row) => speed(row.download_rate),
      ], "暂无已认证连接");
    } catch (error) {
      byId("metrics-status").textContent = `实时统计暂不可用：${error.message}`;
    }
  }

  refresh();
  setInterval(refresh, 2000);
})();
