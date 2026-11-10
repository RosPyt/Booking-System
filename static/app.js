(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const serviceBtns = [...document.querySelectorAll("#svc button")];
  const catBtns = [...document.querySelectorAll(".seg button")];
  const state = { service: null, slot: null, part: null, request: 0 };

  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (t) => `${pad(Math.floor(t / 60))}:${pad(t % 60)}`;
  const inPart = (t) => (state.part === "morning" ? t < 720 : state.part === "afternoon" ? t >= 720 : true);

  async function api(url, options) {
    try {
      const res = await fetch(url, options);
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, data };
    } catch {
      return { ok: false, data: { error: "Πρόβλημα σύνδεσης. Ελέγξτε το internet σας και δοκιμάστε ξανά." } };
    }
  }

  function say(text, isError = false) {
    const box = $("msg");
    box.textContent = text;
    box.className = `msg ${isError ? "err" : "ok"}`;
  }

  function renderSummary() {
    const cat = catBtns.find((b) => b.classList.contains("on"));
    const date = $("date").value;
    const s = state.service?.dataset;
    $("s-cat").textContent = cat ? cat.textContent : "–";
    $("s-svc").textContent = s ? s.name : "–";
    $("s-dur").textContent = s ? `${s.min} λεπτά` : "–";
    $("s-price").textContent = s ? `${s.price} €` : "–";
    $("s-time").textContent = state.slot === null ? "–" : fmt(state.slot);
    $("s-date").textContent = date
      ? new Date(`${date}T00:00`).toLocaleDateString("el-GR", { weekday: "short", day: "numeric", month: "long" })
      : "–";
  }

  function selectService(id) {
    state.service = serviceBtns.find((b) => b.dataset.id === String(id)) || serviceBtns[0] || null;
    if (!state.service) return;
    catBtns.forEach((b) => b.classList.toggle("on", b.dataset.cat === state.service.dataset.cat));
    serviceBtns.forEach((b) => {
      b.hidden = b.dataset.cat !== state.service.dataset.cat;
      b.classList.toggle("on", b === state.service);
    });
  }

  function hint(box, text) {
    box.innerHTML = "";
    const span = document.createElement("span");
    span.className = "hint";
    span.textContent = text;
    box.append(span);
  }

  async function loadSlots() {
    state.slot = null;
    renderSummary();
    const box = $("slots");
    if (!state.service || !$("date").value) return hint(box, "Επιλέξτε ημερομηνία για να δείτε τη διαθεσιμότητα.");

    const ticket = ++state.request; // αγνοούμε παλιές απαντήσεις αν ο χρήστης άλλαξε επιλογή στο μεταξύ
    const { ok, data } = await api(`/api/slots?service=${state.service.dataset.id}&date=${$("date").value}`);
    if (ticket !== state.request) return;
    const slots = ok ? data.slots.filter(inPart) : [];
    if (!slots.length) return hint(box, "Δεν υπάρχουν διαθέσιμες ώρες για την επιλεγμένη ημερομηνία. Παρακαλούμε επιλέξτε άλλη.");

    box.innerHTML = "";
    for (const t of slots) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = fmt(t);
      b.onclick = () => {
        state.slot = t;
        [...box.children].forEach((x) => x.classList.toggle("on", x === b));
        renderSummary();
      };
      box.append(b);
    }
  }

  async function autofill() {
    const text = $("ask").value.trim();
    if (!text) return;
    const button = $("askbtn");
    button.disabled = true;
    const { ok, data: r } = await api("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    button.disabled = false;
    if (!ok) return say(r.error || "Η αυτόματη συμπλήρωση δεν είναι διαθέσιμη. Επιλέξτε χειροκίνητα.", true);

    const sameCat = serviceBtns.find((b) => b.dataset.cat === r.category);
    if (r.service_id) selectService(r.service_id);
    else if (sameCat) selectService(sameCat.dataset.id);
    if (r.date && r.date >= $("date").min && r.date <= $("date").max) $("date").value = r.date;
    state.part = r.part;
    const understood = r.service_id || r.category || r.date;
    say(understood
      ? "Η φόρμα συμπληρώθηκε. Επιλέξτε ώρα και ολοκληρώστε τα στοιχεία σας."
      : "Δεν ήταν δυνατή η αναγνώριση του αιτήματος. Παρακαλούμε επιλέξτε χειροκίνητα.", !understood);
    loadSlots();
  }

  async function book() {
    if (!state.service || !$("date").value || state.slot === null) return say("Παρακαλούμε επιλέξτε ημερομηνία και ώρα.", true);
    const name = $("name").value.trim();
    const phone = $("phone").value.trim();
    if (!name || !phone) return say("Παρακαλούμε συμπληρώστε ονοματεπώνυμο και τηλέφωνο.", true);

    const button = $("book");
    button.disabled = true; // αποφυγή διπλού κλικ
    const { ok, data } = await api("/api/book", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service_id: +state.service.dataset.id, date: $("date").value, start: state.slot, name, phone }),
    });
    button.disabled = false;
    say(data.text || data.error || "Κάτι πήγε στραβά. Δοκιμάστε ξανά.", !ok);
    if (ok) { $("name").value = ""; $("phone").value = ""; }
    loadSlots();
  }

  const chooseService = (id) => { selectService(id); state.part = null; loadSlots(); };
  serviceBtns.forEach((b) => (b.onclick = () => chooseService(b.dataset.id)));
  catBtns.forEach((b) => (b.onclick = () => chooseService(serviceBtns.find((s) => s.dataset.cat === b.dataset.cat).dataset.id)));
  $("date").onchange = () => {
    const input = $("date");
    if (input.value && (input.value < input.min || input.value > input.max)) {
      input.value = "";
      say(`Μπορείτε να κλείσετε ραντεβού από ${input.min} έως ${input.max}.`, true);
    }
    state.part = null;
    loadSlots();
  };
  $("askbtn").onclick = autofill;
  $("ask").onkeydown = (e) => { if (e.key === "Enter") autofill(); };
  $("book").onclick = book;

  selectService();
  renderSummary();
})();
