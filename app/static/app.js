/* Logic Giao diện Xưởng Video TikTok Affiliate (Bản 1.3) */

let STATE = {
  products: [],
  config: {},
  queueStatus: { paused: false, current: null, queue: [], logs: [] },
  reviewFilter: "cho_duyet",
  selectedReviewCardKey: null,
  cropProduct: null,
  cropFrames: {},
  bannerModalProduct: null,
  contentModalProduct: null,
};

const STATE_LABELS = {
  chua_lam: "Chưa làm",
  trong_hang_doi: "Trong hàng đợi",
  dang_lam: "⚙ Đang làm...",
  cho_duyet: "Chờ duyệt",
  da_duyet: "✓ Đã duyệt",
  da_loai: "Đã loại",
  loi: "✗ Lỗi",
};

const VIEWPORT_SPECS = {
  anh_trai: { slotW: 540, slotH: 1280, vpW: 169, vpH: 400 },
  anh_phai: { slotW: 540, slotH: 1280, vpW: 169, vpH: 400 },
  can_canh: { slotW: 1080, slotH: 1920, vpW: 225, vpH: 400 },
};

const TAB_META = {
  "tab-products": {
    title: "Sản phẩm & Tư liệu đầu vào",
    subtitle: "Kéo-thả 3 file ảnh/clip vào từng sản phẩm, kiểm tra khung và bấm Làm video",
  },
  "tab-bulk": {
    title: "Dán Kịch bản AI Hàng loạt",
    subtitle: "Sao chép lệnh mẫu gửi Claude / ChatGPT rồi dán kết quả để tự tạo nhiều sản phẩm cùng lúc",
  },
  "tab-review": {
    title: "Duyệt Video Thành phẩm",
    subtitle: "Xem trước video 9:16 đã ghép giọng & phụ đề động, bấm Duyệt để xuất sang kho đăng",
  },
  "tab-ready": {
    title: "Kho Video Sẵn sàng Đăng",
    subtitle: "Tải trọn bộ file ZIP (MP4 + Caption) về máy tính hoặc điện thoại để đăng lên kênh TikTok",
  },
  "tab-settings": {
    title: "Cài đặt Hệ thống & Khuôn Video",
    subtitle: "Tùy chỉnh giọng đọc AI, màu sắc thương hiệu kênh, chống trùng lặp và phụ đề động",
  },
};

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, options);
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("Phiên đăng nhập đã hết hạn.");
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || `Lỗi máy chủ (${resp.status})`);
  }
  return data;
}

function showToast(msg, type = "info") {
  const box = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ==================== CHUYỂN TAB & SIDEBAR ==================== */
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === tabId);
  });
  const meta = TAB_META[tabId];
  if (meta) {
    document.getElementById("pageHeaderTitle").textContent = meta.title;
    document.getElementById("pageHeaderSubtitle").textContent = meta.subtitle;
  }
  toggleMobileSidebar(false);
  if (tabId === "tab-review") renderReviewGrid();
  if (tabId === "tab-ready") loadReadyVideos();
}

function toggleMobileSidebar(open) {
  const sb = document.getElementById("appSidebar");
  const bd = document.getElementById("sidebarBackdrop");
  if (!sb || !bd) return;
  sb.classList.toggle("open", Boolean(open));
  bd.classList.toggle("hidden", !open);
}

/* ==================== TÀI KHOẢN: LOGIN / LOGOUT / ĐỔI MẬT KHẨU ==================== */
async function loadCurrentUser() {
  try {
    const me = await apiFetch("/api/auth/me");
    const uname = me.username || "admin";
    document.getElementById("currentUsernameDisplay").textContent = uname;
    document.getElementById("userAvatarLetter").textContent = uname.charAt(0).toUpperCase();
    document.getElementById("accNewUsername").value = uname;
  } catch (_) { }
}

async function logoutAccount() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (_) { }
  window.location.href = "/login";
}

function openAccountModal() {
  document.getElementById("accCurrentPassword").value = "";
  document.getElementById("accNewPassword").value = "";
  document.getElementById("accConfirmPassword").value = "";
  document.getElementById("accountModal").classList.remove("hidden");
  toggleMobileSidebar(false);
}

function closeAccountModal() {
  document.getElementById("accountModal").classList.add("hidden");
}

async function submitChangePassword() {
  const newUsername = document.getElementById("accNewUsername").value.trim();
  const curPass = document.getElementById("accCurrentPassword").value;
  const newPass = document.getElementById("accNewPassword").value;
  const confirmPass = document.getElementById("accConfirmPassword").value;

  if (!curPass || !newPass) {
    return showToast("Vui lòng nhập mật khẩu hiện tại và mật khẩu mới.", "error");
  }
  if (newPass !== confirmPass) {
    return showToast("Mật khẩu mới nhập lại không khớp.", "error");
  }

  try {
    const res = await apiFetch("/api/auth/change_password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: curPass,
        new_username: newUsername,
        new_password: newPass,
      }),
    });
    closeAccountModal();
    showToast(`Đã cập nhật tài khoản "${res.username}" thành công!`, "success");
    await loadCurrentUser();
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== TẢI DỮ LIỆU ĐỊNH KỲ ==================== */
async function refreshAll() {
  await Promise.all([loadProducts(), loadStatus(), loadReadyCountOnly()]);
}

async function loadProducts() {
  try {
    const data = await apiFetch("/api/products");
    STATE.products = data.products || [];
    document.getElementById("countProducts").textContent = STATE.products.length;

    let pendingReview = 0;
    STATE.products.forEach((p) => {
      p.videos.forEach((v) => {
        if (v.state === "cho_duyet") pendingReview++;
      });
    });
    document.getElementById("countPendingReview").textContent = pendingReview;

    renderProductsList();
    if (document.getElementById("tab-review").classList.contains("active")) {
      renderReviewGrid();
    }
  } catch (err) {
    console.error(err);
  }
}

async function loadStatus() {
  try {
    const st = await apiFetch("/api/status");
    const prevCurrent = STATE.queueStatus.current ? JSON.stringify(STATE.queueStatus.current) : "";
    const nowCurrent = st.current ? JSON.stringify(st.current) : "";
    const prevLen = STATE.queueStatus.queue_length || 0;

    STATE.queueStatus = st;
    updateQueueUI(st);

    if (prevCurrent !== nowCurrent || prevLen !== (st.queue_length || 0)) {
      loadProducts();
    }
  } catch (err) {
    console.error(err);
  }
}

async function loadReadyCountOnly() {
  try {
    const data = await apiFetch("/api/ready");
    let total = 0;
    (data.days || []).forEach((d) => (total += d.count));
    document.getElementById("countReady").textContent = total;
  } catch (_) { }
}

function updateQueueUI(st) {
  const dot = document.getElementById("queueDot");
  const txt = document.getElementById("headerQueueText");
  const btn = document.getElementById("btnToggleQueue");
  const badge = document.getElementById("logCurrentJobBadge");

  dot.className = "dot " + (st.paused ? "paused" : st.current ? "busy" : "idle");
  btn.textContent = st.paused ? "▶ Tiếp tục" : "⏸ Tạm dừng";

  if (st.current) {
    const jobStr = `${st.current.product} · Video ${st.current.video_no}`;
    txt.textContent = `Đang làm: ${jobStr} (${st.queue_length} chờ)`;
    badge.textContent = `⚙ Đang render: ${jobStr}`;
  } else if (st.paused) {
    txt.textContent = `Đã tạm dừng (${st.queue_length} chờ)`;
    badge.textContent = `⏸ Tạm dừng (${st.queue_length} chờ)`;
  } else {
    txt.textContent = `Hàng đợi: Rảnh (${st.queue_length} chờ)`;
    badge.textContent = st.queue_length > 0 ? `Chờ xử lý: ${st.queue_length}` : "Đang rảnh";
  }

  const logEl = document.getElementById("logConsoleOutput");
  const wasAtBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  logEl.textContent = (st.logs || []).join("\n") || "Chưa có nhật ký.";
  if (wasAtBottom) {
    logEl.scrollTop = logEl.scrollHeight;
  }
}

/* ==================== TAB 1: DANH SÁCH SẢN PHẨM ==================== */
function renderProductsList() {
  const container = document.getElementById("productsList");
  const q = (document.getElementById("searchProductInput").value || "").trim().toLowerCase();

  const filtered = STATE.products.filter((p) => {
    if (!q) return true;
    return p.slug.toLowerCase().includes(q) || (p.ten || "").toLowerCase().includes(q);
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="card center-col" style="padding: 36px;">
        <h3>Chưa có sản phẩm nào phù hợp</h3>
        <p class="muted-text mt-6">Bấm <strong>+ Sản phẩm mới</strong> hoặc sang tab <strong>2. Dán kịch bản</strong> để tạo hàng loạt sản phẩm.</p>
      </div>`;
    return;
  }

  container.innerHTML = filtered
    .map((p) => {
      const slotBoxes = [
        { key: "anh_trai", label: "Ô Trái" },
        { key: "anh_phai", label: "Ô Phải" },
        { key: "can_canh", label: "Cận cảnh" },
      ]
        .map((s) => {
          const info = p.slots[s.key] || {};
          if (info.present) {
            const typeBadge =
              info.media_type === "video"
                ? `<span class="slot-type-badge video">🎬 CLIP</span>`
                : `<span class="slot-type-badge image">🖼 ẢNH</span>`;
            return `
              <div class="slot-thumb-box" title="Nhấp để chọn file khác hoặc kéo-thả file vào ô này (${escapeHtml(info.filename)})"
                   onclick="triggerSlotFileUpload('${p.slug}', '${s.key}')"
                   ondragover="onSlotDragOver(event)"
                   ondrop="onSlotDrop(event, '${p.slug}', '${s.key}')">
                <span class="slot-label-top">${s.label}</span>
                <img src="${info.thumb_url}" loading="lazy" alt="${s.label}" />
                ${typeBadge}
              </div>`;
          }
          return `
            <div class="slot-thumb-box" onclick="triggerSlotFileUpload('${p.slug}', '${s.key}')"
                 ondragover="onSlotDragOver(event)"
                 ondrop="onSlotDrop(event, '${p.slug}', '${s.key}')">
              <span class="slot-label-top">${s.label}</span>
              <div class="slot-empty-placeholder">➕ Kéo-thả hoặc bấm chọn file</div>
            </div>`;
        })
        .join("");

      const chk = (ok, name) => `<span class="chk-pill ${ok ? "ok" : "miss"}">${ok ? "✓" : "✗"} ${name}</span>`;

      const videoRows = p.videos
        .map((v) => {
          const stLabel = STATE_LABELS[v.state] || v.state;
          const durTxt = v.duration ? ` · ${Number(v.duration).toFixed(1)}s` : "";
          const errAttr = v.error ? `title="${escapeHtml(v.error)}"` : "";
          return `
            <div class="video-mini-row">
              <strong>Video ${v.video_no}</strong>
              <div class="v-hook-preview" title="${escapeHtml(v.hook)}">
                ${v.hook ? escapeHtml(v.hook) : '<em style="color:#999">Chưa có kịch bản</em>'}
                ${v.error ? `<div style="color:#cf222e;font-size:11.5px;font-weight:600;margin-top:2px;">⚠ ${escapeHtml(v.error)}</div>` : ""}
              </div>
              <span class="state-badge state-${v.state}" ${errAttr}>${stLabel}${durTxt}</span>
              ${v.state === "cho_duyet"
              ? `<button class="btn btn-xs btn-accent" onclick="switchTab('tab-review'); selectReviewCard('${p.slug}__${v.video_no}')" title="Xem thử và duyệt video này">👁 Xem & Duyệt</button>`
              : v.state === "da_duyet"
                ? `<button class="btn btn-xs btn-primary" onclick="switchTab('tab-ready')" title="Đã duyệt! Bấm để sang mục tải video">📦 Tải về</button>`
                : v.state === "loi"
                  ? `<button class="btn btn-xs btn-secondary" style="border-color:#cf222e;color:#cf222e;" onclick="renderProductVideos('${p.slug}', ${v.video_no})" title="Bấm để chạy lại video này">↺ Làm lại</button>`
                  : v.state === "dang_lam"
                    ? `<button class="btn btn-xs btn-secondary" disabled>⚙ Đang làm...</button>`
                    : v.state === "trong_hang_doi"
                      ? `<button class="btn btn-xs btn-secondary" disabled>⏳ Chờ...</button>`
                      : `<button class="btn btn-xs btn-secondary" onclick="renderProductVideos('${p.slug}', ${v.video_no})" ${!p.ready_to_render || !v.has_script ? "disabled" : ""}>▶ Làm v${v.video_no}</button>`
            }
            </div>`;
        })
        .join("");

      return `
        <div class="product-card"
             ondragover="onCardDragOver(event, this)"
             ondragleave="onCardDragLeave(event, this)"
             ondrop="onCardDrop(event, this, '${p.slug}')">
          <div class="media-strip-col">
            <div class="thumbs-row">${slotBoxes}</div>
            <div class="slot-quick-swap">
              <button class="btn btn-xs btn-secondary" onclick="swapSlots('${p.slug}', 'anh_trai', 'anh_phai')" title="Đổi vị trí Ô Trái và Ô Phải">⇄ Đổi Trái/Phải</button>
              <button class="btn btn-xs btn-secondary" onclick="swapSlots('${p.slug}', 'anh_phai', 'can_canh')" title="Đổi Ô Phải sang Cận cảnh">⇄ Phải/Cận cảnh</button>
              <button class="btn btn-xs btn-ghost" onclick="triggerMultiUpload('${p.slug}')" title="Chọn 3 file cùng lúc">+ Tải 3 file</button>
            </div>
          </div>

          <div class="prod-info-col">
            <div class="prod-header-row">
              <div>
                <div class="prod-title">${escapeHtml(p.ten)}</div>
                <div class="prod-slug">📁 san_pham/${escapeHtml(p.slug)} ${p.link ? `· 🔗 <a href="${escapeHtml(p.link)}" target="_blank">Link SP</a>` : ""}</div>
                <div class="checklist-pills">
                  ${chk(p.slots.anh_trai.present, "Ô Trái")}
                  ${chk(p.slots.anh_phai.present, "Ô Phải")}
                  ${chk(p.slots.can_canh.present, "Cận cảnh")}
                  ${chk(p.has_noi_dung, "Kịch bản")}
                </div>
              </div>
              <div class="prod-actions-bar">
                <button class="btn btn-sm btn-primary" onclick="renderProductVideos('${p.slug}', null)" ${!p.ready_to_render ? "disabled" : ""}>▶ Làm cả 3 video</button>
                <button class="btn btn-sm btn-secondary" onclick="openCropModal('${p.slug}')">✂ Chỉnh khung ảnh</button>
                <button class="btn btn-sm btn-secondary" onclick="openBannerModal('${p.slug}', 1)">👁 Xem banner</button>
                <button class="btn btn-sm btn-secondary" onclick="openContentModal('${p.slug}')">📝 Sửa nội dung</button>
                ${!STATE.config.is_cloud ? `<button class="btn btn-sm btn-ghost" onclick="openProductExplorer('${p.slug}')">📂 Mở thư mục</button>` : ""}
                <button class="btn btn-sm btn-ghost" style="color:#cf222e" onclick="deleteProduct('${p.slug}')">🗑 Xóa</button>
              </div>
            </div>

            <div class="videos-mini-table">${videoRows}</div>
          </div>
        </div>`;
    })
    .join("");
}

/* ==================== KÉO-THẢ & ĐỔI CHỖ TƯ LIỆU ==================== */
function onSlotDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
}

async function onSlotDrop(e, slug, slot) {
  e.preventDefault();
  e.stopPropagation();
  const files = e.dataTransfer.files;
  if (!files || !files.length) return;
  await uploadFilesToProduct(slug, files, files.length === 1 ? slot : null);
}

function onCardDragOver(e, cardEl) {
  e.preventDefault();
  cardEl.classList.add("drag-over");
}

function onCardDragLeave(e, cardEl) {
  cardEl.classList.remove("drag-over");
}

async function onCardDrop(e, cardEl, slug) {
  e.preventDefault();
  cardEl.classList.remove("drag-over");
  const files = e.dataTransfer.files;
  if (!files || !files.length) return;
  await uploadFilesToProduct(slug, files, null);
}

function triggerSlotFileUpload(slug, slot) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "image/*,video/*";
  inp.onchange = () => {
    if (inp.files && inp.files.length) uploadFilesToProduct(slug, inp.files, slot);
  };
  inp.click();
}

function triggerMultiUpload(slug) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.multiple = true;
  inp.accept = "image/*,video/*";
  inp.onchange = () => {
    if (inp.files && inp.files.length) uploadFilesToProduct(slug, inp.files, null);
  };
  inp.click();
}

async function uploadFilesToProduct(slug, fileList, slot) {
  const fd = new FormData();
  fd.append("product", slug);
  if (slot) fd.append("slot", slot);
  Array.from(fileList).forEach((f) => fd.append("files", f));
  try {
    showToast(`Đang tải ${fileList.length} file vào ${slug}...`);
    await apiFetch("/api/product/upload", { method: "POST", body: fd });
    showToast("Đã nhận tư liệu & tự động gán khung!", "success");
    await loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function swapSlots(slug, slotA, slotB) {
  try {
    await apiFetch("/api/product/swap_slots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: slug, slot_a: slotA, slot_b: slotB }),
    });
    showToast("Đã đổi chỗ tư liệu!", "success");
    await loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== HÀNG ĐỢI & RENDER ==================== */
async function renderProductVideos(slug, videoNo = null) {
  try {
    const payload = { product: slug };
    if (videoNo !== null) payload.video_no = videoNo;
    const res = await apiFetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showToast(`Đã thêm ${res.added} video vào hàng đợi!`, "success");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function renderAllPending() {
  try {
    const res = await apiFetch("/api/render_all", { method: "POST" });
    if (res.added === 0) {
      showToast("Không có video Chưa làm / Bị lỗi nào đủ tư liệu để thêm.");
    } else {
      showToast(`Đã thêm ${res.added} video vào hàng đợi tự động!`, "success");
    }
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function toggleQueuePause() {
  const action = STATE.queueStatus.paused ? "resume" : "pause";
  try {
    const res = await apiFetch("/api/queue/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    updateQueueUI(res.status);
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function clearPendingQueue() {
  try {
    const res = await apiFetch("/api/queue/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "clear" }),
    });
    updateQueueUI(res.status);
    await loadProducts();
    showToast("Đã xóa danh sách chờ.");
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== MODAL TRÌNH CHỈNH KHUNG ẢNH (CROP EDITOR) ==================== */
async function openCropModal(slug) {
  try {
    const data = await apiFetch(`/api/frames?product=${encodeURIComponent(slug)}`);
    STATE.cropProduct = slug;
    STATE.cropFrames = data.frames || {};
    document.getElementById("cropModalProductTitle").textContent = slug;
    document.getElementById("cropModal").classList.remove("hidden");

    ["anh_trai", "anh_phai", "can_canh"].forEach((slot) => {
      setupCropSlotDOM(slot, STATE.cropFrames[slot]);
    });
  } catch (err) {
    showToast(err.message, "error");
  }
}

function closeCropModal() {
  document.getElementById("cropModal").classList.add("hidden");
  STATE.cropProduct = null;
}

function setupCropSlotDOM(slot, fInfo) {
  const vp = document.getElementById(`vp_${slot}`);
  const bgImg = document.getElementById(`bg_${slot}`);
  const fgImg = document.getElementById(`fg_${slot}`);
  const slider = document.getElementById(`zslider_${slot}`);
  const zLabel = document.getElementById(`zval_${slot}`);
  const vToggleWrap = document.getElementById(`vtoggle_wrap_${slot}`);
  const vToggle = document.getElementById(`vtoggle_${slot}`);

  if (!fInfo || !fInfo.has_media || !fInfo.preview_url) {
    bgImg.src = "";
    fgImg.src = "";
    fgImg.style.display = "none";
    bgImg.style.display = "none";
    if (vToggleWrap) vToggleWrap.classList.add("hidden");
    return;
  }

  fgImg.style.display = "block";
  bgImg.style.display = "block";
  bgImg.src = fInfo.preview_url;
  fgImg.src = fInfo.preview_url;

  slider.value = fInfo.z || 1.0;
  zLabel.textContent = Number(fInfo.z || 1.0).toFixed(2);

  if (vToggleWrap && vToggle) {
    if (fInfo.media_type === "video") {
      vToggleWrap.classList.remove("hidden");
      vToggle.checked = fInfo.use_video !== false;
      vToggle.onchange = () => {
        STATE.cropFrames[slot].use_video = vToggle.checked;
      };
    } else {
      vToggleWrap.classList.add("hidden");
    }
  }

  fgImg.onload = () => {
    STATE.cropFrames[slot].natW = fgImg.naturalWidth || fInfo.img_w || 1080;
    STATE.cropFrames[slot].natH = fgImg.naturalHeight || fInfo.img_h || 1920;
    applyCropVisualMath(slot);
  };

  bindCropViewportEvents(vp, slot);
}

/* Công thức đặt ảnh giống hệt compute_placement() trong crop.py */
function applyCropVisualMath(slot) {
  const f = STATE.cropFrames[slot];
  if (!f || !f.has_media) return;
  const spec = VIEWPORT_SPECS[slot];
  const imgW = f.natW || f.img_w || 1080;
  const imgH = f.natH || f.img_h || 1920;

  let cx = Math.max(0, Math.min(1, Number(f.cx ?? 0.5)));
  let cy = Math.max(0, Math.min(1, Number(f.cy ?? 0.5)));
  let z = Math.max(0.4, Math.min(3.0, Number(f.z ?? 1.0)));

  const baseS = Math.max(spec.vpW / imgW, spec.vpH / imgH);
  const s = baseS * z;
  const scaledW = imgW * s;
  const scaledH = imgH * s;

  let x = spec.vpW / 2.0 - cx * scaledW;
  let y = spec.vpH / 2.0 - cy * scaledH;

  if (scaledW >= spec.vpW) {
    x = Math.max(spec.vpW - scaledW, Math.min(0, x));
    cx = (spec.vpW / 2.0 - x) / scaledW;
  } else {
    x = (spec.vpW - scaledW) / 2.0;
    cx = 0.5;
  }

  if (scaledH >= spec.vpH) {
    y = Math.max(spec.vpH - scaledH, Math.min(0, y));
    cy = (spec.vpH / 2.0 - y) / scaledH;
  } else {
    y = (spec.vpH - scaledH) / 2.0;
    cy = 0.5;
  }

  f.cx = cx;
  f.cy = cy;
  f.z = z;

  const fgImg = document.getElementById(`fg_${slot}`);
  fgImg.style.width = `${scaledW}px`;
  fgImg.style.height = `${scaledH}px`;
  fgImg.style.transform = `translate(${x}px, ${y}px)`;

  document.getElementById(`zslider_${slot}`).value = z;
  document.getElementById(`zval_${slot}`).textContent = z.toFixed(2);
}

function bindCropViewportEvents(vpEl, slot) {
  if (vpEl.dataset.bound === "1") return;
  vpEl.dataset.bound = "1";

  let dragging = false;
  let startX = 0;
  let startY = 0;
  let startCx = 0.5;
  let startCy = 0.5;

  vpEl.addEventListener("pointerdown", (e) => {
    const f = STATE.cropFrames[slot];
    if (!f || !f.has_media) return;
    dragging = true;
    startX = e.clientX;
    startY = e.clientY;
    startCx = f.cx;
    startCy = f.cy;
    vpEl.setPointerCapture(e.pointerId);
  });

  vpEl.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const f = STATE.cropFrames[slot];
    if (!f || !f.has_media) return;
    const spec = VIEWPORT_SPECS[slot];
    const imgW = f.natW || f.img_w || 1080;
    const imgH = f.natH || f.img_h || 1920;
    const s = Math.max(spec.vpW / imgW, spec.vpH / imgH) * f.z;
    const scaledW = imgW * s;
    const scaledH = imgH * s;

    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    f.cx = Math.max(0, Math.min(1, startCx - dx / scaledW));
    f.cy = Math.max(0, Math.min(1, startCy - dy / scaledH));
    applyCropVisualMath(slot);
  });

  vpEl.addEventListener("pointerup", () => {
    dragging = false;
  });

  vpEl.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const f = STATE.cropFrames[slot];
      if (!f || !f.has_media) return;
      const factor = e.deltaY < 0 ? 1.06 : 1.0 / 1.06;
      f.z = Math.max(0.4, Math.min(3.0, f.z * factor));
      applyCropVisualMath(slot);
    },
    { passive: false }
  );
}

function onCropSliderChange(slot, val) {
  const f = STATE.cropFrames[slot];
  if (!f || !f.has_media) return;
  f.z = parseFloat(val);
  applyCropVisualMath(slot);
}

async function resetSingleSlotAuto(slot) {
  if (!STATE.cropProduct) return;
  try {
    await apiFetch("/api/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product: STATE.cropProduct,
        frames: { [slot]: { reset: true } },
      }),
    });
    await openCropModal(STATE.cropProduct);
    showToast(`Đã đặt lại tự động cho ${slot}!`);
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function resetAllFramesAuto() {
  if (!STATE.cropProduct) return;
  try {
    await apiFetch("/api/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: STATE.cropProduct, reset_auto: true }),
    });
    await openCropModal(STATE.cropProduct);
    showToast("Đã đặt lại tự động cả 3 khung ảnh!", "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function saveFramesAndPreviewBanner() {
  if (!STATE.cropProduct) return;
  const slug = STATE.cropProduct;
  const payloadFrames = {};
  ["anh_trai", "anh_phai", "can_canh"].forEach((s) => {
    const f = STATE.cropFrames[s];
    if (f && f.has_media) {
      payloadFrames[s] = {
        cx: f.cx,
        cy: f.cy,
        z: f.z,
        use_video: f.use_video !== false,
      };
    }
  });
  try {
    await apiFetch("/api/frames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: slug, frames: payloadFrames }),
    });
    closeCropModal();
    await openBannerModal(slug, 1);
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== XEM BANNER & SỬA NỘI DUNG ==================== */
async function openBannerModal(slug, videoNo = 1) {
  STATE.bannerModalProduct = slug;
  document.getElementById("bannerModalTitle").textContent = slug;
  document.getElementById("bannerPreviewModal").classList.remove("hidden");
  await switchBannerVariantPreview(videoNo);
}

async function switchBannerVariantPreview(videoNo) {
  if (!STATE.bannerModalProduct) return;
  [1, 2, 3].forEach((n) => {
    document.getElementById(`btnPrevV${n}`).classList.toggle("active", n === videoNo);
  });
  try {
    const res = await apiFetch("/api/preview_banner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: STATE.bannerModalProduct, video_no: videoNo }),
    });
    document.getElementById("bannerPreviewImage").src = res.banner_url;
  } catch (err) {
    showToast(err.message, "error");
  }
}

function closeBannerModal() {
  document.getElementById("bannerPreviewModal").classList.add("hidden");
}

async function openContentModal(slug) {
  try {
    const data = await apiFetch(`/api/product/content?product=${encodeURIComponent(slug)}`);
    STATE.contentModalProduct = slug;
    document.getElementById("contentModalTitle").textContent = slug;
    document.getElementById("contentModalTextarea").value = data.content || "";
    document.getElementById("contentModal").classList.remove("hidden");
  } catch (err) {
    showToast(err.message, "error");
  }
}

function closeContentModal() {
  document.getElementById("contentModal").classList.add("hidden");
}

async function saveProductContentModal() {
  if (!STATE.contentModalProduct) return;
  try {
    const content = document.getElementById("contentModalTextarea").value;
    await apiFetch("/api/product/content", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: STATE.contentModalProduct, content }),
    });
    closeContentModal();
    showToast("Đã lưu kịch bản noi_dung.txt!", "success");
    await loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== TẠO SẢN PHẨM MỚI & MỞ THƯ MỤC ==================== */
function openNewProductModal() {
  document.getElementById("newProdName").value = "";
  document.getElementById("newProdLink").value = "";
  document.getElementById("newProdHashtag").value = "";
  document.getElementById("newProductModal").classList.remove("hidden");
}

function closeNewProductModal() {
  document.getElementById("newProductModal").classList.add("hidden");
}

async function submitNewProduct() {
  const name = document.getElementById("newProdName").value.trim();
  if (!name) return showToast("Vui lòng nhập tên sản phẩm.", "error");
  const openExp = document.getElementById("newProdOpenExplorer").checked;
  try {
    await apiFetch(`/api/product/new?open_explorer=${openExp}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        ten_hien_thi: name,
        link: document.getElementById("newProdLink").value.trim(),
        hashtag: document.getElementById("newProdHashtag").value.trim(),
      }),
    });
    closeNewProductModal();
    showToast("Đã tạo sản phẩm mới!", "success");
    await loadProducts();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function openProductExplorer(slug) {
  await apiFetch("/api/product/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product: slug }),
  });
}

async function deleteProduct(slug) {
  if (!confirm(`Bạn có chắc muốn xóa toàn bộ sản phẩm "${slug}" và các video bên trong?`)) return;
  try {
    await apiFetch("/api/product/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: slug }),
    });
    showToast(`Đã xóa sản phẩm ${slug}.`, "success");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function openFolder(target, dateFolder = null) {
  await apiFetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, date_folder: dateFolder }),
  });
}

/* ==================== TAB 2: DÁN KỊCH BẢN HÀNG LOẠT ==================== */
async function loadPromptTemplate() {
  try {
    const data = await apiFetch("/api/prompt");
    document.getElementById("promptTemplateBox").value = data.prompt || "";
  } catch (_) { }
}

async function copyPromptTemplate() {
  const txt = document.getElementById("promptTemplateBox").value;
  await navigator.clipboard.writeText(txt);
  showToast("Đã sao chép lệnh mẫu vào bộ nhớ tạm!", "success");
}

async function savePromptTemplate() {
  const txt = document.getElementById("promptTemplateBox").value;
  try {
    await apiFetch("/api/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: txt }),
    });
    showToast("Đã lưu lệnh mẫu thành công!", "success");
  } catch (err) {
    showToast(`Lỗi khi lưu lệnh mẫu: ${err.message}`, "danger");
  }
}

async function resetPromptTemplate() {
  if (!confirm("Bạn có chắc chắn muốn đặt lại lệnh mẫu về mặc định của hệ thống không?")) {
    return;
  }
  try {
    const res = await apiFetch("/api/prompt/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res && res.prompt) {
      document.getElementById("promptTemplateBox").value = res.prompt;
    } else {
      await loadPromptTemplate();
    }
    showToast("Đã khôi phục lệnh mẫu về mặc định!", "success");
  } catch (err) {
    showToast(`Lỗi khi đặt lại: ${err.message}`, "danger");
  }
}

async function previewBulkScripts() {
  const text = document.getElementById("bulkPasteInput").value;
  if (!text.trim()) return showToast("Ô kịch bản hàng loạt đang trống.", "error");
  try {
    const res = await apiFetch("/api/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, preview_only: true }),
    });
    const html = res.items
      .map(
        (it) =>
          `<div style="padding:6px 0;border-bottom:1px solid #eee;">
            <strong>📁 ${escapeHtml(it.slug)}</strong> (${escapeHtml(it.ten)}) — <strong>${it.video_count} video</strong>
          </div>`
      )
      .join("");
    document.getElementById("bulkPreviewResult").innerHTML = `
      <div class="tip-banner">Phát hiện <strong>${res.count} sản phẩm</strong> hợp lệ:${html}</div>`;
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function saveBulkScripts() {
  const text = document.getElementById("bulkPasteInput").value;
  if (!text.trim()) return showToast("Vui lòng dán nội dung kịch bản trước.", "error");
  try {
    const res = await apiFetch("/api/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, preview_only: false }),
    });
    showToast(`Đã lưu thành công ${res.count} sản phẩm!`, "success");
    await loadProducts();
    switchTab("tab-products");
  } catch (err) {
    showToast(err.message, "error");
  }
}

/* ==================== TAB 3: DUYỆT VIDEO & PHÍM TẮT ==================== */
function setReviewFilter(filter) {
  STATE.reviewFilter = filter;
  document.querySelectorAll("#reviewFilterPills .pill").forEach((el) => {
    el.classList.toggle("active", el.dataset.filter === filter);
  });
  renderReviewGrid();
}

function renderReviewGrid() {
  const grid = document.getElementById("reviewGrid");
  const cards = [];

  STATE.products.forEach((p) => {
    p.videos.forEach((v) => {
      const f = STATE.reviewFilter;
      if (f === "all") {
        if (!v.video_url && v.state !== "loi") return;
      } else if (v.state !== f) {
        return;
      }
      cards.push({ p, v, key: `${p.slug}__${v.video_no}` });
    });
  });

  if (cards.length === 0) {
    grid.innerHTML = `
      <div class="card center-col" style="grid-column: 1 / -1; padding: 36px;">
        <h3>Không có video nào ở mục này</h3>
        <p class="muted-text mt-6">Khi hàng đợi làm xong video, chúng sẽ xuất hiện tại mục Chờ duyệt.</p>
      </div>`;
    return;
  }

  grid.innerHTML = cards
    .map(({ p, v, key }) => {
      const selectedCls = STATE.selectedReviewCardKey === key ? "selected" : "";
      const videoEl = v.video_url
        ? `<video src="${v.video_url}" controls preload="metadata"></video>`
        : `<div style="color:#ff8b8b;padding:18px;text-align:center;font-size:13px;">⚠ Lỗi: ${escapeHtml(v.error)}</div>`;

      return `
        <div class="review-card ${selectedCls}" tabindex="0" data-key="${key}"
             data-slug="${p.slug}" data-vno="${v.video_no}"
             onclick="selectReviewCard('${key}')">
          <div class="review-video-wrap">${videoEl}</div>
          <div class="review-card-body">
            <div class="review-meta-top">
              <strong>${escapeHtml(p.slug)} · v${v.video_no}</strong>
              <span class="state-badge state-${v.state}">${STATE_LABELS[v.state] || v.state}</span>
            </div>
            <div class="review-hook-text">${escapeHtml(v.hook)}</div>
            <div class="muted-text" style="display:flex;justify-content:space-between;align-items:center;">
              <span>
                ${v.duration ? `⏱ ${Number(v.duration).toFixed(1)}s` : ""}
                ${v.tts_provider ? ` · 🔊 ${escapeHtml(v.tts_provider)}` : ""}
              </span>
              ${v.download_url ? `<a class="btn btn-xs btn-secondary" href="${v.download_url}" onclick="event.stopPropagation()">⬇ Tải MP4</a>` : ""}
            </div>
            <div class="review-actions">
              <button class="btn btn-sm btn-success" onclick="event.stopPropagation(); reviewAction('${p.slug}', ${v.video_no}, 'approve')" ${!v.video_url ? "disabled" : ""}>✓ Duyệt</button>
              <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); reviewAction('${p.slug}', ${v.video_no}, 'reject')">✗ Loại</button>
              <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); reviewAction('${p.slug}', ${v.video_no}, 'redo')">↻ Làm lại</button>
            </div>
          </div>
        </div>`;
    })
    .join("");
}

function selectReviewCard(key) {
  STATE.selectedReviewCardKey = key;
  document.querySelectorAll(".review-card").forEach((el) => {
    el.classList.toggle("selected", el.dataset.key === key);
  });
}

async function reviewAction(slug, videoNo, action) {
  try {
    await apiFetch("/api/video/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product: slug, video_no: videoNo, action }),
    });
    const msgMap = {
      approve: "★ Đã duyệt & xuất sang Sẵn sàng đăng!",
      reject: "Đã đánh dấu loại video.",
      redo: "Đã đưa video vào hàng đợi làm lại.",
    };
    showToast(msgMap[action] || "Đã cập nhật!", "success");
    await refreshAll();
  } catch (err) {
    showToast(err.message, "error");
  }
}

document.addEventListener("keydown", (e) => {
  if (!document.getElementById("tab-review").classList.contains("active")) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  if (!STATE.selectedReviewCardKey) return;

  const card = document.querySelector(`.review-card[data-key="${STATE.selectedReviewCardKey}"]`);
  if (!card) return;
  const slug = card.dataset.slug;
  const vno = parseInt(card.dataset.vno, 10);
  const vid = card.querySelector("video");

  if (e.code === "Space" && vid) {
    e.preventDefault();
    vid.paused ? vid.play() : vid.pause();
  } else if (e.key.toLowerCase() === "a") {
    reviewAction(slug, vno, "approve");
  } else if (e.key.toLowerCase() === "x") {
    reviewAction(slug, vno, "reject");
  } else if (e.key.toLowerCase() === "r") {
    reviewAction(slug, vno, "redo");
  }
});

/* ==================== TAB 4: SẴN SÀNG ĐĂNG ==================== */
async function loadReadyVideos() {
  const container = document.getElementById("readyDaysContainer");
  try {
    const data = await apiFetch("/api/ready");
    const days = data.days || [];
    let total = 0;
    days.forEach((d) => (total += d.count));
    document.getElementById("countReady").textContent = total;

    if (days.length === 0) {
      container.innerHTML = `
        <div class="card center-col" style="padding: 36px;">
          <h3>Chưa có video nào trong san_sang_dang/</h3>
          <p class="muted-text mt-6">Hãy bấm <strong>✓ Duyệt</strong> ở tab 3 để chuyển video và caption sang đây.</p>
        </div>`;
      return;
    }

    container.innerHTML = days
      .map((d) => {
        const itemsHtml = d.items
          .map(
            (it, idx) => `
            <div class="ready-item">
              <video src="${it.video_url}" controls preload="metadata"></video>
              <div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <strong>${escapeHtml(it.filename)}</strong>
                  <span class="muted-text">${it.size_mb} MB</span>
                </div>
                <div style="font-size:11.5px;color:#0969da;font-weight:600;margin-top:2px;">🕒 Gợi ý: ${escapeHtml(it.post_slot_hint)}</div>
                <textarea class="caption-box" id="cap_${d.date}_${idx}" readonly>${escapeHtml(it.caption)}</textarea>
                <div class="btn-group">
                  <button class="btn btn-xs btn-primary" onclick="copyCaptionById('cap_${d.date}_${idx}')">📋 Sao chép Caption</button>
                  ${it.download_url ? `<a class="btn btn-xs btn-secondary" href="${it.download_url}">⬇ Tải MP4</a>` : ""}
                </div>
              </div>
            </div>`
          )
          .join("");

        return `
          <div class="day-group-card">
            <div class="day-header">
              <h3>📅 Ngày ${escapeHtml(d.date)} (${d.count} video)</h3>
              <div class="btn-group">
                ${d.zip_url ? `<a class="btn btn-sm btn-primary" href="${d.zip_url}">📦 Tải ZIP ngày ${escapeHtml(d.date)}</a>` : ""}
                ${!STATE.config.is_cloud ? `<button class="btn btn-sm btn-secondary" onclick="openFolder('san_sang_dang', '${d.date}')">📂 Mở thư mục ngày</button>` : ""}
              </div>
            </div>
            <div class="ready-items-grid">${itemsHtml}</div>
          </div>`;
      })
      .join("");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function copyCaptionById(elId) {
  const txt = document.getElementById(elId).value;
  await navigator.clipboard.writeText(txt);
  showToast("Đã chép Caption vào bộ nhớ tạm!", "success");
}

/* ==================== TAB 5: CÀI ĐẶT & HỒ SƠ KÊNH ==================== */
async function loadConfigIntoUI() {
  try {
    const cfg = await apiFetch("/api/config");
    STATE.config = cfg;

    // Ẩn nút mở Explorer trên Cloud & bật thông báo lưu ý cho gói Render Free
    document.querySelectorAll(".local-only-btn").forEach((el) => {
      el.classList.toggle("hidden", Boolean(cfg.is_cloud));
    });
    const cloudBanner = document.getElementById("cloudNoticeBanner");
    if (cloudBanner) {
      cloudBanner.classList.toggle("hidden", !cfg.is_cloud);
    }

    // Render Channel Presets trên Header
    const chSelect = document.getElementById("headerChannelSelect");
    const presets = cfg.channel_presets || {};
    chSelect.innerHTML = Object.entries(presets)
      .map(([k, v]) => `<option value="${k}" ${cfg.active_channel === k ? "selected" : ""}>${escapeHtml(v.name || k)}</option>`)
      .join("");

    const boolKeys = [
      "voice_enabled",
      "hook_boost_enabled",
      "anti_duplicate_enabled",
      "auto_swap_slots_v2",
      "auto_vary_band_color",
      "subtitle_enabled",
      "hook_uppercase",
      "banner_zoom",
    ];
    boolKeys.forEach((k) => {
      const el = document.getElementById(`cfg_${k}`);
      if (el) el.checked = Boolean(cfg[k]);
    });

    const valKeys = [
      "tts_provider",
      "edge_voice",
      "edge_rate",
      "edge_pitch",
      "hook_boost_rate",
      "hook_boost_pitch",
      "cloud_tts_provider",
      "cloud_tts_voice",
      "cloud_tts_api_key",
      "cloud_tts_model",
      "cloud_tts_base_url",
      "voicestudio_url",
      "voice_engine",
      "voice_seed",
      "voice_profile_id",
      "voice_instruct",
      "voice_gap_seconds",
      "band_color",
      "band_color_v2",
      "band_color_v3",
      "subtitle_words_per_chunk",
      "subtitle_font_size",
      "subtitle_color",
      "hook_font_size",
      "sharpen",
      "crf",
      "video_encoder",
      "min_seconds",
      "font_path",
      "music_path",
      "default_hashtags",
    ];
    valKeys.forEach((k) => {
      const el = document.getElementById(`cfg_${k}`);
      if (el && cfg[k] !== undefined && cfg[k] !== null) {
        el.value = cfg[k];
      }
    });

    onChangeTTSProviderUI();
  } catch (err) {
    console.error(err);
  }
}

function onChangeTTSProviderUI() {
  const prov = document.getElementById("cfg_tts_provider").value;
  document.getElementById("ttsGroupEdge").classList.toggle("hidden", prov !== "edge");
  document.getElementById("ttsGroupCloud").classList.toggle("hidden", prov !== "cloud");
  document.getElementById("ttsGroupVoiceStudio").classList.toggle("hidden", prov !== "voicestudio");
}

function collectSettingsFromUI() {
  return {
    voice_enabled: document.getElementById("cfg_voice_enabled").checked,
    tts_provider: document.getElementById("cfg_tts_provider").value,
    edge_voice: document.getElementById("cfg_edge_voice").value,
    edge_rate: document.getElementById("cfg_edge_rate").value.trim(),
    edge_pitch: document.getElementById("cfg_edge_pitch").value.trim(),
    hook_boost_enabled: document.getElementById("cfg_hook_boost_enabled").checked,
    hook_boost_rate: document.getElementById("cfg_hook_boost_rate").value.trim(),
    hook_boost_pitch: document.getElementById("cfg_hook_boost_pitch").value.trim(),
    cloud_tts_provider: document.getElementById("cfg_cloud_tts_provider").value,
    cloud_tts_voice: document.getElementById("cfg_cloud_tts_voice").value.trim(),
    cloud_tts_api_key: document.getElementById("cfg_cloud_tts_api_key").value.trim(),
    cloud_tts_model: document.getElementById("cfg_cloud_tts_model").value.trim(),
    cloud_tts_base_url: document.getElementById("cfg_cloud_tts_base_url").value.trim(),
    voicestudio_url: document.getElementById("cfg_voicestudio_url").value.trim(),
    voice_engine: document.getElementById("cfg_voice_engine").value.trim(),
    voice_seed: parseInt(document.getElementById("cfg_voice_seed").value, 10) || 1234,
    voice_profile_id: document.getElementById("cfg_voice_profile_id").value.trim(),
    voice_instruct: document.getElementById("cfg_voice_instruct").value.trim(),
    voice_gap_seconds: parseFloat(document.getElementById("cfg_voice_gap_seconds").value) || 0.15,
    anti_duplicate_enabled: document.getElementById("cfg_anti_duplicate_enabled").checked,
    auto_swap_slots_v2: document.getElementById("cfg_auto_swap_slots_v2").checked,
    auto_vary_band_color: document.getElementById("cfg_auto_vary_band_color").checked,
    band_color: document.getElementById("cfg_band_color").value,
    band_color_v2: document.getElementById("cfg_band_color_v2").value,
    band_color_v3: document.getElementById("cfg_band_color_v3").value,
    subtitle_enabled: document.getElementById("cfg_subtitle_enabled").checked,
    subtitle_words_per_chunk: parseInt(document.getElementById("cfg_subtitle_words_per_chunk").value, 10) || 4,
    subtitle_font_size: parseInt(document.getElementById("cfg_subtitle_font_size").value, 10) || 52,
    subtitle_color: document.getElementById("cfg_subtitle_color").value,
    hook_font_size: parseInt(document.getElementById("cfg_hook_font_size").value, 10) || 60,
    sharpen: parseFloat(document.getElementById("cfg_sharpen").value) || 0.5,
    crf: parseInt(document.getElementById("cfg_crf").value, 10) || 20,
    hook_uppercase: document.getElementById("cfg_hook_uppercase").checked,
    banner_zoom: document.getElementById("cfg_banner_zoom").checked,
    video_encoder: document.getElementById("cfg_video_encoder").value,
    min_seconds: parseFloat(document.getElementById("cfg_min_seconds").value) || 18.0,
    font_path: document.getElementById("cfg_font_path").value.trim(),
    music_path: document.getElementById("cfg_music_path").value.trim(),
    default_hashtags: document.getElementById("cfg_default_hashtags").value.trim(),
  };
}

async function saveSettingsForm() {
  try {
    const payload = collectSettingsFromUI();
    await apiFetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showToast("Đã lưu toàn bộ cài đặt!", "success");
    await loadConfigIntoUI();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function onSwitchChannelPreset(channelKey) {
  try {
    await apiFetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_channel: channelKey, apply_channel_preset: true }),
    });
    await loadConfigIntoUI();
    showToast(`Đã áp dụng Hồ sơ Kênh: ${channelKey}`, "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function checkTTSConnection() {
  await saveSettingsForm();
  try {
    const res = await apiFetch("/api/voice/check");
    const box = document.getElementById("voiceCheckStatus");
    box.textContent = (res.ok ? "✅ " : "⚠ ") + res.message;
    box.style.color = res.ok ? "#1a7f37" : "#cf222e";
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function fetchVoiceStudioProfiles() {
  try {
    const data = await apiFetch("/api/voice/profiles");
    const list = data.profiles || [];
    if (!list.length) return showToast("Chưa có profile nào hoặc chưa bật VoiceStudio.");
    document.getElementById("cfg_voice_profile_id").value = list[0].id;
    showToast(`Tìm thấy ${list.length} giọng. Đã điền: ${list[0].name}`, "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function testVoicePreview() {
  const text = document.getElementById("voiceTestInput").value.trim();
  if (!text) return showToast("Nhập câu cần nghe thử.", "error");
  const statusEl = document.getElementById("voiceCheckStatus");
  statusEl.textContent = "⏳ Đang tạo giọng đọc thử...";
  try {
    const res = await apiFetch("/api/voice/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, config_override: collectSettingsFromUI() }),
    });
    const audio = document.getElementById("voicePreviewAudio");
    audio.src = res.audio_url;
    audio.classList.remove("hidden");
    audio.play();
    statusEl.textContent = "✅ Đã tạo xong giọng đọc thử!";
    statusEl.style.color = "#1a7f37";
  } catch (err) {
    statusEl.textContent = "✗ " + err.message;
    statusEl.style.color = "#cf222e";
  }
}

/* ==================== LOG DOCK ==================== */
function toggleLogDockSize() {
  const dock = document.getElementById("logDock");
  if (dock.classList.contains("expanded")) {
    dock.classList.remove("expanded");
    dock.classList.add("collapsed");
  } else if (dock.classList.contains("collapsed")) {
    dock.classList.remove("collapsed");
  } else {
    dock.classList.add("expanded");
  }
}

/* ==================== KHỞI ĐỘNG ==================== */
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadCurrentUser(), loadConfigIntoUI(), loadPromptTemplate(), refreshAll()]);
  setInterval(loadStatus, 3000);
});
