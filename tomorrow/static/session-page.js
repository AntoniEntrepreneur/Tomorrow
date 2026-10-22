
import { request, state } from "./session-state.js";
import { fetchActivitySuggestion } from "./session-state.js";
import { autofill, checklistItemsPayload, checklistPayload, clockLabel, clockValue, endClock, fmtDur, isNextDay, isTouched, markTouched, restoreAutofilled, SUGGESTIBLE_FIELDS, TIMING_FIELDS, toClock, toMin, toWakeMin, untouchedField } from "./construction-shared.js";


    function markTemplateDirty() {
      if (!state.templateMode) return;
      state.templateDirty = true;
      document.getElementById("template-saved").textContent = "Unsaved changes";
    }

    function cloneTemplate(value) {
      return JSON.parse(JSON.stringify(value));
    }

    window.addEventListener("beforeunload", event => {
      if (!state.templateMode || !state.templateDirty) return;
      event.preventDefault();
      event.returnValue = "You have unsaved template changes.";
      return event.returnValue;
    });

    document.getElementById("template-editor").addEventListener("input", markTemplateDirty);
    document.getElementById("template-reset").addEventListener("click", () => {
      if (!state.templateMode || !state.templateInitial) return;
      if (state.templateDirty && !window.confirm("Discard unsaved template changes?")) return;
      const source = state.templateInitial.template;
      state.templateDraft = cloneTemplate(state.templateInitial.draft);
      state.templateArmedFlex = null;
      const form = document.getElementById("template-editor");
      form.elements.name.value = source.name || "";
      form.elements.weekday.value = source.weekday || "";
      state.templateDirty = false;
      document.getElementById("template-saved").textContent = "Reset";
      renderTemplateEntries();
    });
    document.getElementById("template-back").addEventListener("click", () => {
      window.location.href = "/library";
    });

    function esc(value) {
      return String(value).replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    }

    function checklistName(checklistId) {
      if (!checklistId || !state.current) return "";
      const entry = (state.current.checklists || []).find(item => item.id === checklistId);
      return entry ? entry.name : "";
    }

    function checklistRows(checklistId) {
      const entries = state.current ? state.current.checklists : (state.templateDraft && state.templateDraft.checklists) || [];
      if (!checklistId) return [];
      const entry = entries.find(item => item.id === checklistId);
      return entry ? (entry.items || []) : [];
    }

    function checklistField(selectedId, selectedItems) {
      const selected = selectedId || "";
      // A reference item carries no `checklist_items` of its own; its rows
      // editor is prefilled from the referenced Checklist's current rows so
      // the first edit has something concrete to detach away from.
      const rows = (selectedItems && selectedItems.length
        ? selectedItems
        : checklistRows(selected)
      ).join("\n");
      const entries = state.current ? state.current.checklists : (state.templateDraft && state.templateDraft.checklists) || [];
      const options = entries.map(entry =>
        '<option value="' + esc(entry.id) + '"' +
        (entry.id === selected ? " selected" : "") + ">" +
        esc(entry.name) + "</option>"
      ).join("");
      return '<label>Checklist <select name="checklist" data-checklist-select="1"' +
        (selected || rows ? ' data-touched="1"' : "") + ">" +
        '<option value="">None</option>' + options + "</select></label>" +
        '<label>One-time rows (one per line)<textarea name="checklist_items"' +
        (rows ? ' data-touched="1"' : "") + '>' + esc(rows) + "</textarea></label>";
    }

    // Activity Template autocomplete: a matching Activity Template pre-fills its
    // start/duration and Checklist; otherwise a bare Checklist name match fills
    // only the Checklist. Touched fields are never overridden.
    function applyActivitySuggestion(form, suggestion) {
      const checklist = untouchedField(form, "checklist");
      if (!suggestion || suggestion.kind !== "activity") {
        restoreAutofilled(form, TIMING_FIELDS);
        if (checklist) checklist.value = (suggestion && suggestion.checklist_id) || "";
        return;
      }
      if (checklist) checklist.value = suggestion.checklist || "";
      const endMode = form.dataset.durationMode === "end";
      if (suggestion.start && !(endMode && isTouched(form, "end"))) {
        autofill(form, "start", suggestion.start);
      }
      autofill(form, "duration_minutes", suggestion.duration_minutes);
      if (endMode && form.start && form.start.value) {
        autofill(form, "end", endClock(clockValue(form.start), suggestion.duration_minutes));
      }
    }

    async function suggestFromName(form) {
      if (!form || !form.name) return;
      const request = ++state.latestSuggestRequest;
      let suggestion;
      try {
        suggestion = await fetchActivitySuggestion(form.name.value.trim());
      } catch (error) {
        console.error(error);
        return;
      }
      if (request !== state.latestSuggestRequest || !form.isConnected) return;
      applyActivitySuggestion(form, suggestion);
    }

    function heightPx(durationMin, total, floor) {
      return Math.max(floor, Math.round((durationMin / Math.max(total, 1)) * 520));
    }

    function railRows(session) {
      const wakeClock = session.bounds.wake;
      const sleep = toWakeMin(session.bounds.sleep, wakeClock);
      const occupied = (session.anchors || []).map(item => ({
        kind: "anchor",
        id: item.id,
        name: item.name,
        start: item.start,
        durationMin: item.duration_minutes,
        end: endClock(item.start, item.duration_minutes),
        checklist: item.checklist,
        source: item.source
      })).concat((session.flexes || []).filter(item => item.start).map(item => ({
        kind: "flex",
        id: item.id,
        name: item.name,
        start: item.start,
        durationMin: item.duration_minutes,
        end: endClock(item.start, item.duration_minutes),
        checklist: item.checklist,
        source: item.source
      }))).sort((a, b) => toWakeMin(a.start, wakeClock) - toWakeMin(b.start, wakeClock));
      const rows = [];
      let cursor = 0;
      for (const item of occupied) {
        const start = toWakeMin(item.start, wakeClock);
        if (start > cursor) {
          rows.push({
            kind: "gap",
            start: toClock(toMin(wakeClock) + cursor),
            end: item.start,
            durationMin: start - cursor
          });
        }
        rows.push(item);
        cursor = Math.max(cursor, toWakeMin(item.end, wakeClock));
      }
      if (sleep > cursor) {
        rows.push({
          kind: "gap",
          start: toClock(toMin(wakeClock) + cursor),
          end: session.bounds.sleep,
          durationMin: sleep - cursor
        });
      }
      return rows;
    }

    function sessionUndoBlocked() {
      return state.sheetKind === "edit";
    }

    const BLOCKER_FLASH_MS = 5000;
    let blockerFlashTimer = null;

    function blockersEl() {
      return document.getElementById("blockers");
    }

    function hideBlockers() {
      if (blockerFlashTimer) {
        clearTimeout(blockerFlashTimer);
        blockerFlashTimer = null;
      }
      const el = blockersEl();
      el.textContent = "";
      el.hidden = true;
    }

    function flashBlockers(blockers) {
      if (!blockers.length) return;
      hideBlockers();
      const el = blockersEl();
      el.textContent = blockers.join(" ");
      el.hidden = false;
      blockerFlashTimer = setTimeout(hideBlockers, BLOCKER_FLASH_MS);
    }

    // A showing caption describes the Submit attempt that raised it. Once the
    // Session moves on, it is stale — drop it rather than let it run its 5s out.
    function dropStaleBlockers(blockers) {
      const el = blockersEl();
      if (!el.hidden && el.textContent !== blockers.join(" ")) hideBlockers();
    }

    const TOAST_TIMEOUT_MS = 3000;
    let toastTimer = null;

    function hideToast() {
      if (toastTimer) {
        clearTimeout(toastTimer);
        toastTimer = null;
      }
      const el = document.getElementById("toast");
      if (el) {
        el.hidden = true;
        el.textContent = "";
      }
    }

    function getToastEl() {
      let el = document.getElementById("toast");
      if (!el) {
        el = document.createElement("div");
        el.id = "toast";
        el.className = "toast";
        el.setAttribute("role", "status");
        el.setAttribute("aria-live", "polite");
        el.hidden = true;
        el.addEventListener("click", hideToast);
        document.body.appendChild(el);
      }
      return el;
    }

    function showToast(message) {
      hideToast();
      const el = getToastEl();
      el.textContent = message;
      el.hidden = false;
      toastTimer = setTimeout(hideToast, TOAST_TIMEOUT_MS);
    }

    function setChromeEnabled() {
      if (!state.current) return;
      const blocked = sessionUndoBlocked();
      document.getElementById("undo").disabled = blocked || !state.current.can_undo;
      document.getElementById("redo").disabled = blocked || !state.current.can_redo;
    }

    function renderRail(session) {
      clearGapHover();
      const wakeClock = session.bounds.wake;
      const total = Math.max(1, toWakeMin(session.bounds.sleep, wakeClock));
      document.getElementById("rail").innerHTML = railRows(session).map(row => {
        const startLabel = clockLabel(row.start, wakeClock);
        const endLabel = row.end ? clockLabel(row.end, wakeClock) : row.end;
        if (row.kind === "gap") {
          const armed = state.armedFlexId ? " armed" : "";
          const cta = state.armedFlexId ? "Place here" : "Place Flex";
          return '<button type="button" class="gap' + armed + '" data-kind="gap" data-start="' +
            esc(row.start) + '" data-end="' + esc(row.end) + '" data-duration="' + row.durationMin + '" style="min-height:' +
            heightPx(row.durationMin, total, 40) + 'px">' +
            '<span class="time-tag">' + esc(startLabel) + "</span>" +
            "<span>Gap · " + esc(fmtDur(row.durationMin)) + "</span>" +
            '<span class="cta">' + cta + "</span></button>";
        }
        const checklistLabel = checklistName(row.checklist);
        const icloudTag = row.source === "icloud" ? '<span class="icloud-tag">📅 iCloud</span>' : "";
        const dailyTag = row.source === "daily" ? '<span class="daily-tag">🔁 daily</span>' : "";
        return '<button type="button" class="block ' + row.kind + '" data-kind="' + row.kind +
          '" data-id="' + esc(row.id) + '" style="min-height:' + heightPx(row.durationMin, total, 52) + 'px">' +
          '<span class="time-tag">' + esc(startLabel) + "</span>" +
          '<div class="block-title">' + esc(row.name) + icloudTag + dailyTag + "</div>" +
          (checklistLabel ? '<div class="block-checklist">' + esc(checklistLabel) + "</div>" : "") +
          '<div class="block-range">' + esc(startLabel) + "–" + esc(endLabel) +
          " · " + esc(fmtDur(row.durationMin)) + "</div></button>";
      }).join("");
    }

    function renderTray(session) {
      const unplaced = (session.flexes || []).filter(item => !item.start);
      const tray = document.getElementById("tray");
      if (!unplaced.length) {
        tray.classList.add("empty");
        tray.innerHTML =
          '<div class="tray-label">Unplaced Flex — Place / Change Duration / Drop any time</div>' +
          "<div>No unplaced Flex.</div>";
        return;
      }
      tray.classList.remove("empty");
      tray.innerHTML =
        '<div class="tray-label">Unplaced Flex — Place / Change Duration / Drop any time</div>' +
        '<div class="tray-chips">' + unplaced.map(item =>
          '<div class="flex-chip' + (state.armedFlexId === item.id ? " armed" : "") +
          '" data-arm="' + esc(item.id) + '">' +
          '<span class="name">' + esc(item.name) +
          (item.source === "daily" ? '<span class="daily-tag">🔁 daily</span>' : "") + "</span>" +
          '<span class="meta">' + esc(fmtDur(item.duration_minutes)) + " · unplaced</span>" +
          '<div class="ops">' +
          '<button type="button" data-edit-flex="' + esc(item.id) + '">Edit</button>' +
          '<button type="button" data-place="' + esc(item.id) + '">Place</button>' +
          '<button type="button" data-change-duration="' + esc(item.id) + '">Change Duration</button>' +
          '<button type="button" data-flex-to-todo="' + esc(item.id) + '">Make To-do</button>' +
          '<button type="button" data-drop="' + esc(item.id) + '">Drop</button>' +
          "</div></div>"
        ).join("") + "</div>";
    }

    function renderDrafts(session) {
      const drafts = session.drafts || [];
      const list = document.getElementById("drafts");
      if (!drafts.length) {
        list.classList.add("empty");
        list.innerHTML = "";
        return;
      }
      list.classList.remove("empty");
      list.innerHTML =
        '<div class="drafts-label">Drafts</div>' +
        drafts.map(item =>
          '<div class="draft-chip">' +
          '<div class="row"><span>' + esc(item.name) +
          (item.source === "icloud" ? ' <span class="icloud-tag">📅 iCloud</span>' : "") +
          "</span>" +
          '<button type="button" data-promote="' + esc(item.id) + '">Edit</button>' +
          '<button type="button" data-drop-draft="' + esc(item.id) + '">Drop</button>' +
          "</div>" +
          (item.note ? '<div class="draft-note">' + esc(item.note) + "</div>" : "") +
          "</div>"
        ).join("");
    }

    function renderTodos(session) {
      const todos = session.todos || [];
      const tray = document.getElementById("todos-tray");
      if (!todos.length) {
        tray.classList.add("empty");
        tray.innerHTML =
          '<div class="tray-label">To-dos — sometime tomorrow, no time needed</div>' +
          "<div>No To-dos.</div>";
        return;
      }
      tray.classList.remove("empty");
      tray.innerHTML =
        '<div class="tray-label">To-dos — sometime tomorrow, no time needed</div>' +
        '<div class="tray-chips">' + todos.map(item =>
          '<div class="todo-chip" data-edit-todo="' + esc(item.id) + '">' +
          '<span class="name">' + esc(item.name) + "</span>" +
          (item.note ? '<div class="note">' + esc(item.note) + "</div>" : "") +
          '<div class="ops">' +
          '<button type="button" data-todo-to-flex="' + esc(item.id) + '">Make Flex</button>' +
          '<button type="button" data-todo-to-anchor="' + esc(item.id) + '">Make Anchor</button>' +
          '<button type="button" data-drop-todo="' + esc(item.id) + '">Drop</button>' +
          "</div></div>"
        ).join("") + "</div>";
    }

    function render(session) {
      state.current = session;
      if (state.armedFlexId) {
        const stillUnplaced = (session.flexes || []).some(
          item => item.id === state.armedFlexId && !item.start
        );
        if (!stillUnplaced) state.armedFlexId = null;
      }
      document.title = session.plan_date_label;
      document.getElementById("plan-date").textContent = session.plan_date_label;
      const weatherBits = [];
      if (session.weather_name) {
        weatherBits.push('<span class="name">' + esc(session.weather_name) + "</span>");
      }
      if (session.weather_one_liner) weatherBits.push(esc(session.weather_one_liner));
      document.getElementById("weather").innerHTML = weatherBits.join(" · ");
      dropStaleBlockers(session.blockers || []);
      document.getElementById("wake-cap").textContent = "↑ " + session.bounds.wake + " wake";
      document.getElementById("sleep-cap").textContent =
        clockLabel(session.bounds.sleep, session.bounds.wake) + " sleep ↓";
      renderTemplateOffer(session);
      renderRail(session);
      renderDrafts(session);
      renderTray(session);
      renderTodos(session);
      setChromeEnabled();
    }

    function renderTemplateOffer(session) {
      document.getElementById("template-offer").hidden = !session.show_template_offer;
    }

    function openSheet(html, kind) {
      const backdrop = document.getElementById("sheet-backdrop");
      document.getElementById("sheet").innerHTML = html;
      backdrop.hidden = false;
      backdrop.classList.add("open");
      state.sheetOpen = true;
      state.sheetKind = kind || "edit";
      setChromeEnabled();
      const first = document.getElementById("sheet").querySelector("input, button");
      if (first) first.focus();
    }

    function closeSheet() {
      const backdrop = document.getElementById("sheet-backdrop");
      backdrop.classList.remove("open");
      backdrop.hidden = true;
      document.getElementById("sheet").innerHTML = "";
      state.sheetOpen = false;
      state.sheetKind = null;
      setChromeEnabled();
    }

    function durationFields(start, durationMin, startLabelId) {
      return '<div class="row">' +
        '<label' + (startLabelId ? ' id="' + startLabelId + '"' : "") + '>Start <input name="start" type="time" required value="' + esc(start || "") + '"></label>' +
        '<label class="timing-field" id="duration-label">Duration (min) <input name="duration_minutes" type="number" min="1" required value="' +
        esc(durationMin || "") + '"></label>' +
        '<label class="timing-field" id="end-label">Ends at <input name="end" type="time"></label>' +
        "</div>" +
        '<p class="field-error" id="end-error" hidden>End must be after start.</p>';
    }

    function setDurationMode(form, mode) {
      const asEnd = mode === "end";
      form.dataset.durationMode = mode;
      const durationLabel = form.querySelector("#duration-label");
      const endLabel = form.querySelector("#end-label");
      if (durationLabel) durationLabel.classList.toggle("is-derived", asEnd);
      if (durationLabel) durationLabel.classList.toggle("is-authoritative", !asEnd);
      if (endLabel) endLabel.classList.toggle("is-derived", !asEnd);
      if (endLabel) endLabel.classList.toggle("is-authoritative", asEnd);
      if (form.duration_minutes) form.duration_minutes.required = !asEnd;
      if (form.end) form.end.required = asEnd;
      document.getElementById("end-error").hidden = true;
    }

    function initDurationToggle(form) {
      setDurationMode(form, "duration");
      form.addEventListener("input", event => {
        if (event.target.name === "duration_minutes") setDurationMode(form, "duration");
        if (event.target.name === "end") setDurationMode(form, "end");
        if (event.target.name === "start" || event.target.name === "end") {
          document.getElementById("end-error").hidden = true;
        }
        updateTimingCounterpart(form);
      });
      form.addEventListener("change", event => {
        if (event.target.name === "duration_minutes") setDurationMode(form, "duration");
        if (event.target.name === "end") setDurationMode(form, "end");
        updateTimingCounterpart(form);
      });
      updateTimingCounterpart(form);
    }

    function updateTimingCounterpart(form) {
      if (!form.start || !form.duration_minutes || !form.end) return;
      const start = form.start.value;
      if (!start) return;
      if (form.dataset.durationMode === "end") {
        if (!form.end.value) return;
        const duration = toWakeMin(clockValue(form.end), clockValue(start));
        if (duration > 0) form.duration_minutes.value = duration;
      } else {
        const duration = Number(form.duration_minutes.value);
        if (Number.isFinite(duration) && duration > 0) form.end.value = endClock(start, duration);
      }
    }

    function resolveDurationMinutes(form) {
      if (form.dataset.durationMode === "end") {
        const diff = toWakeMin(clockValue(form.end), clockValue(form.start));
        if (!(diff > 0)) {
          document.getElementById("end-error").hidden = false;
          return null;
        }
        return diff;
      }
      return Number(form.duration_minutes.value);
    }

    function formFields(name, start, durationMin) {
      return '<label>Name <input name="name" required value="' + esc(name || "") + '"></label>' +
        durationFields(start, durationMin);
    }

    function findFlex(itemId) {
      return (state.current.flexes || []).find(item => item.id === itemId);
    }

    function findDraft(itemId) {
      return (state.current.drafts || []).find(item => item.id === itemId);
    }

    function findTodo(itemId) {
      return (state.current.todos || []).find(item => item.id === itemId);
    }

    function gapRows() {
      return railRows(state.current).filter(row => row.kind === "gap");
    }

    function sheetAddFlex() {
      openSheet(
        "<h2>Add Flex</h2><p class=\"hint\">Unplaced Flex lands in the tray. Place it whenever you notice a Gap.</p>" +
        "<form id=\"add-flex\">" +
        '<label>Name <input name="name" required></label>' +
        '<label>Duration (min) <input name="duration_minutes" type="number" min="1" required value="45"></label>' +
        checklistField("") +
        '<div class="actions"><button class="primary" type="submit">Add Flex</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "stamp"
      );
    }

    function sheetAddDraft() {
      openSheet(
        "<h2>Add Draft</h2><p class=\"hint\">Optional capture. Promote to Anchor or Flex, or Drop, before Submit.</p>" +
        "<form id=\"add-draft\">" +
        '<label>Name <input name="name" required></label>' +
        '<div class="actions"><button class="primary" type="submit">Add Draft</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "stamp"
      );
    }

    function sheetPromote(item) {
      const strippedName = item.stripped_name || item.name;
      const clashCaption = item.clash_caption || null;
      const suggestedStart = clashCaption ? "" : (item.suggested_start || "09:00");
      const suggestedEnd = item.suggested_end || null;
      // 30 mirrors DEFAULT_SUGGESTED_DURATION_MINUTES in tomorrow/session.py.
      const suggestedDuration = item.suggested_duration_minutes || 30;
      const defaultKind = item.default_kind || "anchor";
      openSheet(
        "<h2>Edit Draft · " + esc(item.name) + "</h2>" +
        '<p class="hint">A new opaque id is minted. The Draft’s id does not leak.</p>' +
        '<form id="promote-draft" data-id="' + esc(item.id) + '" data-original-name="' + esc(item.name) + '" data-stripped-name="' + esc(strippedName) + '">' +
        '<label>Name <input name="name" required value="' + esc(strippedName) + '"></label>' +
        '<label>Promote to <select name="kind">' +
        '<option value="anchor"' + (defaultKind === "anchor" ? " selected" : "") + '>Anchor</option>' +
        '<option value="flex"' + (defaultKind === "flex" ? " selected" : "") + '>Flex</option>' +
        '<option value="todo">To-do</option>' +
        "</select></label>" +
        durationFields(suggestedStart, suggestedDuration, "promote-start-label") +
        (clashCaption ? '<p class="field-error" id="promote-clash-caption">' + esc(clashCaption) + "</p>" : "") +
        '<p class="hint" id="promote-flex-hint" hidden>Flex lands unplaced in the tray. Place it whenever you notice a Gap.</p>' +
        '<p class="hint" id="promote-todo-hint" hidden>To-do needs nothing else — its note carries over if it has one.</p>' +
        checklistField("") +
        '<div class="actions"><button class="primary" type="submit">Promote</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button>' +
        '<button type="button" class="danger" data-drop-draft="' + esc(item.id) + '">Drop</button></div></form>'
      );
      const form = document.getElementById("promote-draft");
      initDurationToggle(form);
      if (suggestedEnd) {
        setDurationMode(form, "end");
        form.end.value = suggestedEnd;
      }
      const kind = form.querySelector('[name="kind"]');
      kind.addEventListener("change", () => syncPromoteFields(form));
      syncPromoteFields(form);
      // A field the name-parse actually supplied must win over the same
      // field supplied by a matching Activity Template, so mark it touched
      // before suggestFromName runs (autofill only overwrites untouched
      // fields).
      const nameSuppliedFields = [];
      if (item.suggested_start) nameSuppliedFields.push("start");
      if (item.suggested_end) nameSuppliedFields.push("end");
      if (item.suggested_duration_minutes) nameSuppliedFields.push("duration_minutes");
      markTouched(form, nameSuppliedFields);
      suggestFromName(form);
    }

    function sheetEditDraft(item) {
      sheetPromote(item);
    }

    function syncPromoteFields(form) {
      const asFlex = form.kind.value === "flex";
      const asTodo = form.kind.value === "todo";
      if (form.dataset.originalName !== undefined) {
        form.name.value = asTodo ? form.dataset.originalName : form.dataset.strippedName;
      }
      form.start.required = !asFlex && !asTodo;
      document.getElementById("promote-start-label").hidden = asFlex || asTodo;
      const endLabel = document.getElementById("end-label");
      if (endLabel) endLabel.hidden = asFlex || asTodo;
      const endError = document.getElementById("end-error");
      if (endError && (asFlex || asTodo)) endError.hidden = true;
      document.getElementById("promote-flex-hint").hidden = !asFlex;
      document.getElementById("promote-todo-hint").hidden = !asTodo;
      if (form.checklist) form.checklist.closest("label").hidden = asTodo;
      const row = form.querySelector(".row");
      if (row) row.hidden = asTodo;
      form.duration_minutes.required = !asTodo && form.dataset.durationMode !== "end";
      if ((asFlex || asTodo) && form.dataset.durationMode === "end") setDurationMode(form, "duration");
    }

    function sheetAddTodo() {
      openSheet(
        "<h2>Add To-do</h2><p class=\"hint\">No start, no duration — just something to do sometime tomorrow.</p>" +
        "<form id=\"add-todo\">" +
        '<label>Name <input name="name" required></label>' +
        '<label>Note <textarea name="note" rows="3"></textarea></label>' +
        '<div class="actions"><button class="primary" type="submit">Add To-do</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "stamp"
      );
    }

    function sheetEditTodo(item) {
      openSheet(
        "<h2>To-do · " + esc(item.name) + "</h2>" +
        '<form id="edit-todo" data-id="' + esc(item.id) + '">' +
        '<label>Name <input name="name" required value="' + esc(item.name) + '"></label>' +
        '<label>Note <textarea name="note" rows="3">' + esc(item.note || "") + '</textarea></label>' +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        '<button type="button" class="ghost" data-todo-to-flex="' + esc(item.id) + '">Make Flex</button>' +
        '<button type="button" class="ghost" data-todo-to-anchor="' + esc(item.id) + '">Make Anchor</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button>' +
        '<button type="button" class="danger" data-drop-todo="' + esc(item.id) + '">Drop</button></div></form>'
      );
    }

    function sheetTodoToFlex(item) {
      openSheet(
        "<h2>Make Flex · " + esc(item.name) + "</h2>" +
        '<p class="hint">The note is discarded. Undo brings it back.</p>' +
        '<form id="todo-to-flex" data-id="' + esc(item.id) + '">' +
        '<label>Duration (min) <input name="duration_minutes" type="number" min="1" required value="30"></label>' +
        '<div class="actions"><button class="primary" type="submit">Make Flex</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>'
      );
    }

    function sheetTodoToAnchor(item) {
      openSheet(
        "<h2>Make Anchor · " + esc(item.name) + "</h2>" +
        '<p class="hint">The note is discarded. Undo brings it back.</p>' +
        '<form id="todo-to-anchor" data-id="' + esc(item.id) + '">' +
        durationFields("09:00", 30) +
        '<div class="actions"><button class="primary" type="submit">Make Anchor</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>'
      );
      initDurationToggle(document.getElementById("todo-to-anchor"));
    }

    function sheetPlace(item) {
      const opts = gapRows().map(gap =>
        '<button type="button" data-place-at="' + esc(item.id) + '" data-start="' + esc(gap.start) + '">' +
        esc(gap.start) + "–" + esc(gap.end) + " · " + esc(fmtDur(gap.durationMin)) + "</button>"
      ).join("");
      openSheet(
        "<h2>Place Flex · " + esc(item.name) + " (" + esc(fmtDur(item.duration_minutes)) + ")</h2>" +
        '<p class="hint">Snap to a Gap start, or type a clock time.</p>' +
        '<div class="choice-row">' + (opts || "<span>No Gaps.</span>") + "</div>" +
        '<form id="place-flex" data-id="' + esc(item.id) + '">' +
        '<label>Start <input name="start" type="time" required></label>' +
        '<div class="actions"><button class="primary" type="submit">Place</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>'
      );
    }

    function sheetChangeDuration(item) {
      openSheet(
        "<h2>Change Duration · " + esc(item.name) + "</h2>" +
        '<form id="change-duration-flex" data-id="' + esc(item.id) + '">' +
        '<label>New duration (min) <input name="duration_minutes" type="number" min="1" required value="' +
        esc(item.duration_minutes) + '"></label>' +
        '<div class="actions"><button class="primary" type="submit">Change Duration</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>'
      );
    }

    function sheetGapPlace(start, end) {
      const unplaced = (state.current.flexes || []).filter(item => !item.start);
      const opts = unplaced.map(item =>
        '<button type="button" data-place-at="' + esc(item.id) + '" data-start="' + esc(start) + '">' +
        esc(item.name) + " · " + esc(fmtDur(item.duration_minutes)) + "</button>"
      ).join("");
      openSheet(
        "<h2>Place into this Gap</h2>" +
        '<p class="hint">Gap ' + esc(start) + "–" + esc(end) + ". Stamp Flex to add to the tray; clicking a Gap Places it.</p>" +
        '<div class="choice-row">' + (opts || "<span>No unplaced Flex.</span>") + "</div>" +
        '<div class="actions"><button type="button" class="ghost" data-close>Cancel</button></div>'
      );
    }

    function saveToLibraryButton(item, kind) {
      if (item.checklist_kind !== "literal") return "";
      return '<button type="button" class="ghost" data-promote-checklist="' +
        esc(item.id) + '" data-promote-checklist-kind="' + esc(kind) + '">Save to Library</button>';
    }

    function sheetEditFlex(item) {
      const placedHint = item.start
        ? esc(item.start) + " · " + esc(fmtDur(item.duration_minutes))
        : "Unplaced · " + esc(fmtDur(item.duration_minutes));
      openSheet(
        "<h2>Flex · " + esc(item.name) + "</h2>" +
        '<p class="hint">' + placedHint + "</p>" +
        '<form id="edit-flex" data-id="' + esc(item.id) + '">' +
        '<label>Name <input name="name" required value="' + esc(item.name) + '"></label>' +
        '<label>Duration (min) <input name="duration_minutes" type="number" min="1" required value="' +
        esc(item.duration_minutes) + '"></label>' +
        checklistField(item.checklist, item.checklist_items) +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        '<button type="button" class="ghost" data-place="' + esc(item.id) + '">Place</button>' +
        '<button type="button" class="ghost" data-change-duration="' + esc(item.id) + '">Change Duration</button>' +
        '<button type="button" class="ghost" data-flex-to-todo="' + esc(item.id) + '">Make To-do</button>' +
        saveToLibraryButton(item, "flex") +
        '<button type="button" class="ghost" data-close>Cancel</button>' +
        '<button type="button" class="danger" data-drop="' + esc(item.id) + '">Drop</button></div></form>'
      );
      markTouched(document.getElementById("edit-flex"), TIMING_FIELDS);
      suggestFromName(document.getElementById("edit-flex"));
    }

    function sheetAddAnchor() {
      openSheet(
        "<h2>Add Anchor</h2><form id=\"add-anchor\">" +
        formFields("", "", 60) +
        checklistField("") +
        '<div class="actions"><button class="primary" type="submit">Add Anchor</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "stamp"
      );
      initDurationToggle(document.getElementById("add-anchor"));
    }

    function sheetEditAnchor(item) {
      openSheet(
        "<h2>Edit Anchor</h2><form id=\"edit-anchor\" data-id=\"" + esc(item.id) + "\">" +
        formFields(item.name, item.start, item.duration_minutes) +
        checklistField(item.checklist, item.checklist_items) +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        saveToLibraryButton(item, "anchor") +
        '<button type="button" class="ghost" data-close>Cancel</button>' +
        '<button type="button" class="danger" data-remove="' + esc(item.id) + '">Remove</button></div></form>'
      );
      initDurationToggle(document.getElementById("edit-anchor"));
      markTouched(document.getElementById("edit-anchor"), TIMING_FIELDS);
      suggestFromName(document.getElementById("edit-anchor"));
    }

    function templateEntryForm(kind, index, sourceKind) {
      const entry = kind === "activity"
        ? (state.templateDraft[sourceKind === "anchor" ? "anchors" : "flexes"][index] || {})
        : (state.templateDraft[kind === "anchor" ? "anchors" : "flexes"][index] || {});
      if (kind === "activity") {
        const options = (state.templateDraft.activityOptions || []).map(option =>
          '<option value="' + esc(option.id) + '"' + (option.id === entry.activity ? " selected" : "") + '>' +
          esc(option.name) + "</option>").join("");
        const checklistOptions = (state.templateDraft.checklists || []).map(option =>
          '<option value="' + esc(option.id) + '"' +
          (entry.checklist_overridden && option.id === entry.checklist ? " selected" : "") + ">" +
          esc(option.name) + "</option>").join("");
        openSheet(
          "<h2>" + (index === -1 ? "Add " : "Edit ") + "Activity Template</h2>" +
          '<form id="template-activity-entry" data-index="' + index + '" data-source-kind="' + (sourceKind || "") + '">' +
          '<label>Shared template <select name="activity" required>' + options + '</select></label>' +
          '<label>Shape <select name="shape"><option value="flex">Flex</option><option value="anchor">Anchor</option></select><button type="button" class="ghost" data-reset-field="shape">Reset</button></label>' +
          '<label>Name override (optional) <input name="name" value="' + esc(entry.name_overridden ? entry.name : "") + '"><button type="button" class="ghost" data-reset-field="name">Reset</button></label>' +
          '<label>Checklist override (optional) <select name="checklist"><option value="">Inherit</option>' + checklistOptions + '</select><button type="button" class="ghost" data-reset-field="checklist">Reset</button></label>' +
          '<label id="activity-start-label">Start override (Anchor) <input name="start" type="time" value="' + esc(entry.start || "") + '"><button type="button" class="ghost" data-reset-field="timing">Reset timing</button></label>' +
          '<label class="timing-field" id="activity-duration-label">Duration override <input name="duration" type="number" min="1" value="' + esc(entry.duration || "") + '"></label>' +
          '<label class="timing-field" id="activity-end-label">End override <input name="end" type="time" value="' + esc(entry.end || "") + '"></label>' +
          '<p class="hint">Leave an override blank to inherit. Resetting shape also resets its timing.</p>' +
          '<div class="actions"><button class="primary" type="submit">Update</button>' +
          (index >= 0 && (sourceKind === "anchor" || entry.shape === "anchor") ? '<button type="button" class="ghost" id="template-make-flex" data-index="' + index + '" data-activity="true">Make Flex</button>' : '') +
          (index >= 0 ? '<button type="button" class="danger" id="template-drop-entry" data-index="' + index + '" data-kind="' + (sourceKind || "anchor") + '">Drop</button>' : '') +
          '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
          "edit"
        );
        document.querySelector("#template-activity-entry [name=shape]").value = entry.shape || "flex";
        const activityForm = document.getElementById("template-activity-entry");
        activityForm.dataset.durationMode = entry.end ? "end" : "duration";
        function syncActivityTemplateShape() {
          const isAnchor = activityForm.elements.shape.value === "anchor";
          const startLabel = document.getElementById("activity-start-label");
          const endLabel = document.getElementById("activity-end-label");
          if (startLabel) startLabel.hidden = !isAnchor;
          if (endLabel) endLabel.hidden = !isAnchor;
        }
        function updateActivityTemplateTiming() {
          syncActivityTemplateShape();
          const duration = activityForm.elements.duration;
          const end = activityForm.elements.end;
          const start = activityForm.elements.start.value;
          const asEnd = activityForm.dataset.durationMode === "end";
          document.getElementById("activity-duration-label").classList.toggle("is-derived", asEnd);
          document.getElementById("activity-duration-label").classList.toggle("is-authoritative", !asEnd);
          document.getElementById("activity-end-label").classList.toggle("is-derived", !asEnd);
          document.getElementById("activity-end-label").classList.toggle("is-authoritative", asEnd);
          if (!start) return;
          if (asEnd && end.value) {
            const span = toWakeMin(clockValue(end), clockValue(activityForm.elements.start));
            if (span > 0) duration.value = span;
          } else if (!asEnd && Number(duration.value) > 0) {
            end.value = endClock(start, Number(duration.value));
          }
        }
        activityForm.addEventListener("input", event => {
          if (event.target.name === "duration") activityForm.dataset.durationMode = "duration";
          if (event.target.name === "end") activityForm.dataset.durationMode = "end";
          if (["start", "duration", "end"].includes(event.target.name)) {
            activityForm.dataset.timingTouched = "1";
            if (event.target.name === "start") activityForm.elements.shape.value = event.target.value ? "anchor" : "flex";
            updateActivityTemplateTiming();
          }
        });
        activityForm.elements.shape.addEventListener("change", () => {
          activityForm.dataset.timingTouched = "1";
          if (activityForm.elements.shape.value === "flex") {
            const duration = Number(activityForm.elements.duration.value);
            if (duration > 0) activityForm.elements.duration.value = duration;
          }
          updateActivityTemplateTiming();
        });
        updateActivityTemplateTiming();
        return;
      }
      const duration = entry.duration || entry.duration_minutes || "";
      const timing = kind === "anchor"
        ? formFields(entry.name || "", entry.start || "", duration)
        : '<label>Name <input name="name" required value="' + esc(entry.name || "") + '"></label>' +
          '<label>Duration (min) <input name="duration_minutes" type="number" min="1" required value="' + esc(duration) + '"></label>';
      openSheet(
        "<h2>" + (index === -1 ? "Add " : "Edit ") + (kind === "anchor" ? "Anchor" : "Flex") + "</h2>" +
        '<form id="template-entry" data-kind="' + kind + '" data-index="' + index + '">' +
        timing +
        checklistField(entry.checklist) +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        (index >= 0 && kind === "anchor" ? '<button type="button" class="ghost" id="template-make-flex" data-index="' + index + '">Make Flex</button>' : '') +
        (index >= 0 ? '<button type="button" class="danger" id="template-drop-entry" data-index="' + index + '" data-kind="' + kind + '">Drop</button>' : '') +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "edit"
      );
      if (kind === "anchor") {
        const form = document.getElementById("template-entry");
        initDurationToggle(form);
        const authority = entry.end ? "end" : "duration";
        form.end.value = entry.end || (entry.start && duration ? endClock(entry.start, duration) : "");
        setDurationMode(form, authority);
      }
    }

    function templateRailRows() {
      const wakeClock = state.templateDraft.bounds.wake;
      const sleep = toWakeMin(state.templateDraft.bounds.sleep, wakeClock);
      const occupied = (state.templateDraft.anchors || []).map((item, index) => {
        const durationMin = item.end
          ? toWakeMin(item.end, item.start)
          : Number(item.duration || item.duration_minutes || 0);
        const end = item.end || endClock(item.start, durationMin);
        return {
          kind: "anchor",
          originalIndex: index,
          name: item.name || (item.activity ? ("Activity: " + item.activity) : "Anchor"),
          start: item.start,
          durationMin: durationMin,
          end: end,
          checklist: item.checklist,
          daily: Boolean(item.daily),
          activity: item.activity,
          overlap: false
        };
      }).sort((a, b) => toWakeMin(a.start, wakeClock) - toWakeMin(b.start, wakeClock));

      for (let i = 0; i < occupied.length - 1; i++) {
        const cur = occupied[i];
        const nxt = occupied[i + 1];
        if (toWakeMin(cur.end, wakeClock) > toWakeMin(nxt.start, wakeClock)) {
          cur.overlap = true;
          nxt.overlap = true;
        }
      }

      const rows = [];
      let cursor = 0;
      for (const item of occupied) {
        const start = toWakeMin(item.start, wakeClock);
        if (start > cursor) {
          rows.push({
            kind: "gap",
            start: toClock(toMin(wakeClock) + cursor),
            end: item.start,
            durationMin: start - cursor
          });
        }
        rows.push(item);
        cursor = Math.max(cursor, toWakeMin(item.end, wakeClock));
      }
      if (sleep > cursor) {
        rows.push({
          kind: "gap",
          start: toClock(toMin(wakeClock) + cursor),
          end: state.templateDraft.bounds.sleep,
          durationMin: sleep - cursor
        });
      }
      return rows;
    }

    function renderTemplateEntries() {
      clearGapHover();
      renderBounds(state.templateDraft.bounds);
      const wakeClock = state.templateDraft.bounds.wake;
      const total = Math.max(1, toWakeMin(state.templateDraft.bounds.sleep, wakeClock));
      const rail = document.getElementById("rail");
      const rows = templateRailRows();

      rail.innerHTML = rows.map(row => {
        const startLabel = clockLabel(row.start, wakeClock);
        const endLabel = row.end ? clockLabel(row.end, wakeClock) : row.end;
        if (row.kind === "gap") {
          const armed = state.templateArmedFlex ? " armed" : "";
          const cta = state.templateArmedFlex ? "Place here" : "Place Flex";
          return '<button type="button" class="gap' + armed + '" data-template-gap="true" data-start="' +
            esc(row.start) + '" data-end="' + esc(row.end) + '" data-duration="' + row.durationMin + '" style="min-height:' +
            heightPx(row.durationMin, total, 40) + 'px">' +
            '<span class="time-tag">' + esc(startLabel) + "</span>" +
            "<span>Gap · " + esc(fmtDur(row.durationMin)) + "</span>" +
            '<span class="cta">' + cta + "</span></button>";
        }
        const checklistLabel = checklistName(row.checklist);
        const dailyTag = row.daily ? '<span class="daily-tag">🔁 daily</span>' : "";
        const overlapClass = row.overlap ? " overlap" : "";
        return '<button type="button" class="block anchor' + overlapClass + '" data-template-entry="' +
          (row.activity ? "activity" : "anchor") + '" data-template-source-kind="anchor" data-template-index="' +
          row.originalIndex + '" style="min-height:' + heightPx(row.durationMin, total, 52) + 'px">' +
          '<span class="time-tag">' + esc(startLabel) + "</span>" +
          '<div class="block-title">' + esc(row.name) + dailyTag + "</div>" +
          (checklistLabel ? '<div class="block-checklist">' + esc(checklistLabel) + "</div>" : "") +
          '<div class="block-range">' + esc(startLabel) + "–" + esc(endLabel) +
          " · " + esc(fmtDur(row.durationMin)) + "</div></button>";
      }).join("");

      renderTemplateTray();
    }

    function renderTemplateTray() {
      const tray = document.getElementById("tray");
      tray.className = "tray";
      const flexes = state.templateDraft.flexes || [];
      const daily = state.templateDraft.dailyActivities || [];
      const totalCount = flexes.length + daily.length;
      if (!totalCount) {
        tray.classList.add("empty");
        tray.innerHTML =
          '<div class="tray-label">Unplaced Flex & Daily Activities — Place / Change Duration / Drop any time</div>' +
          "<div>No unplaced Flex or Daily Activities.</div>";
        return;
      }
      tray.classList.remove("empty");
      const flexChips = flexes.map((entry, index) => {
        const isArmed = state.templateArmedFlex && state.templateArmedFlex.source === "flex" && state.templateArmedFlex.index === index;
        const armedClass = isArmed ? " armed" : "";
        const dailyTag = entry.daily ? '<span class="daily-tag">🔁 daily</span>' : "";
        const dur = entry.duration || entry.duration_minutes || 0;
        return '<div class="flex-chip' + armedClass + '" data-template-chip="true" data-source="flex" data-index="' + index + '">' +
          '<span class="name">' + esc(entry.name || (entry.activity ? ("Activity: " + entry.activity) : ("Flex " + (index + 1)))) + dailyTag + '</span>' +
          '<span class="meta">' + esc(fmtDur(dur)) + ' · unplaced</span>' +
          '<div class="ops">' +
          '<button type="button" data-template-action="edit" data-source="flex" data-index="' + index + '">Edit</button>' +
          '<button type="button" data-template-action="place" data-source="flex" data-index="' + index + '">Place</button>' +
          '<button type="button" data-template-action="change-duration" data-source="flex" data-index="' + index + '">Change Duration</button>' +
          '<button type="button" data-template-action="drop" data-source="flex" data-index="' + index + '">Drop</button>' +
          '</div></div>';
      });

      const dailyChips = daily.map((entry, index) => {
        const isArmed = state.templateArmedFlex && state.templateArmedFlex.source === "daily" && state.templateArmedFlex.index === index;
        const armedClass = isArmed ? " armed" : "";
        const dur = entry.duration_minutes || entry.duration || 0;
        return '<div class="flex-chip' + armedClass + '" data-template-chip="true" data-source="daily" data-index="' + index + '">' +
          '<span class="name">' + esc(entry.name) + '<span class="daily-tag">🔁 daily</span></span>' +
          '<span class="meta">' + esc(fmtDur(dur)) + ' · unplaced</span>' +
          '<div class="ops">' +
          '<button type="button" data-template-action="place" data-source="daily" data-index="' + index + '">Place</button>' +
          '<button type="button" data-template-action="change-duration" data-source="daily" data-index="' + index + '">Change Duration</button>' +
          '<button type="button" data-template-action="drop" data-source="daily" data-index="' + index + '">Drop</button>' +
          '</div></div>';
      });

      tray.innerHTML =
        '<div class="tray-label">Unplaced Flex & Daily Activities — Place / Change Duration / Drop any time</div>' +
        '<div class="tray-chips">' + flexChips.concat(dailyChips).join("") + '</div>';
    }

    function placeTemplateArmedFlex(start) {
      clearGapHover();
      if (!state.templateArmedFlex) return;
      const { source, index } = state.templateArmedFlex;
      state.templateArmedFlex = null;
      if (source === "flex") {
        const entry = state.templateDraft.flexes.splice(index, 1)[0];
        entry.start = start;
        entry.shape = "anchor";
        delete entry.end;
        state.templateDraft.anchors.push(entry);
      } else if (source === "daily") {
        const item = state.templateDraft.dailyActivities.splice(index, 1)[0];
        state.templateDraft.anchors.push({
          activity: item.id,
          name: item.name,
          start: start,
          duration: item.duration_minutes,
          checklist: item.checklist,
          shape: "anchor",
          daily: true
        });
      }
      markTemplateDirty();
      renderTemplateEntries();
    }

    function templateSheetChangeDuration(source, index) {
      const item = source === "flex"
        ? state.templateDraft.flexes[index]
        : state.templateDraft.dailyActivities[index];
      const dur = item.duration || item.duration_minutes || 30;
      openSheet(
        "<h2>Change Duration · " + esc(item.name || ("Activity: " + item.activity)) + "</h2>" +
        '<form id="template-change-duration" data-source="' + source + '" data-index="' + index + '">' +
        '<label>Duration (min) <input name="duration" type="number" min="1" required value="' + esc(dur) + '"></label>' +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>',
        "edit"
      );
    }

    function renderBounds(bounds) {
      document.getElementById("wake-cap").textContent = "↑ " + bounds.wake + " wake";
      document.getElementById("sleep-cap").textContent =
        clockLabel(bounds.sleep, bounds.wake) + " sleep ↓";
    }

    function sheetEditBound(which) {
      const bounds = state.templateMode ? state.templateDraft.bounds : state.current.bounds;
      const value = bounds[which];
      const label = which === "wake" ? "Wake" : "Sleep";
      openSheet(
        "<h2>Edit " + label + "</h2><form id=\"edit-bounds\" data-which=\"" + which + "\">" +
        "<label>" + label + ' <input name="clock" type="time" required value="' + esc(value) + '"></label>' +
        '<div class="actions"><button class="primary" type="submit">Update</button>' +
        '<button type="button" class="ghost" data-close>Cancel</button></div></form>'
      );
    }

    let mutating = false;
    async function mutate(path, payload) {
      if (mutating) return null;
      mutating = true;
      const submitButton = document.querySelector("#sheet button[type='submit']");
      if (submitButton) submitButton.disabled = true;
      try {
        const response = await request(path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) {
          showSheetError(data.error || "Something went wrong.");
          return null;
        }
        closeSheet();
        render(data);
        return data;
      } finally {
        mutating = false;
        if (submitButton) submitButton.disabled = false;
      }
    }

    function showSheetError(message) {
      const sheet = document.getElementById("sheet");
      const form = sheet.querySelector("form");
      if (!form) return;
      let el = form.querySelector(".field-error");
      if (!el) {
        el = document.createElement("p");
        el.className = "field-error";
        form.insertBefore(el, form.firstChild);
      }
      el.textContent = message;
      el.hidden = false;
    }

    async function loadSession() {
      const templateQuery = new URLSearchParams(window.location.search).get("template");
      if (templateQuery !== null) {
        state.templateMode = true;
        const templateId = templateQuery === "new" ? "" : templateQuery;
        const response = await request("/api/template?id=" + encodeURIComponent(templateId));
        const template = await response.json();
        document.querySelector(".kicker").textContent = "Day Template";
        document.getElementById("plan-date").textContent = template.name || "New Template";
        document.getElementById("weather").textContent = "Reusable template · changes stay in template mode";
        document.getElementById("template-editor").hidden = false;
        document.getElementById("template-editor").elements.name.value = template.name;
        document.getElementById("template-editor").elements.weekday.value = template.weekday || "";
        state.templateDraft = {
          anchors: (template.anchors || []).map(entry => ({...entry})),
          flexes: (template.flexes || []).map(entry => ({...entry})),
          bounds: {...template.bounds},
          activityOptions: template.activity_templates || [],
          dailyActivities: (template.daily_activities || []).map(entry => ({...entry})),
          checklists: template.checklists || []
        };
        state.templateInitial = cloneTemplate({
          template,
          draft: state.templateDraft
        });
        state.templateDirty = false;
        state.templateArmedFlex = null;
        document.body.classList.add("template-mode");
        renderTemplateEntries();
        document.querySelector(".stamps").hidden = false;
        document.getElementById("template-offer").hidden = true;
        document.getElementById("submit").hidden = true;
        document.getElementById("undo").hidden = true;
        document.getElementById("redo").hidden = true;
        document.getElementById("reset").hidden = true;
        document.getElementById("todos-tray").hidden = true;
        document.getElementById("template-mode-label").textContent =
          "Reusable Day Template · " + (template.template_id || "new");
        document.getElementById("template-editor").onsubmit = async (event) => {
          event.preventDefault();
          const form = new FormData(event.target);
          const result = await request("/api/template", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              action: "save",
              template_id: template.template_id,
              name: form.get("name"),
              weekday: form.get("weekday") || null,
              wake: state.templateDraft.bounds.wake,
              sleep: state.templateDraft.bounds.sleep,
              anchors: state.templateDraft.anchors,
              flexes: state.templateDraft.flexes
            })
          }).then((r) => r.json());
          if (result.error) {
            alert(result.error);
            return;
          }
          document.getElementById("template-saved").textContent = "Saved";
          state.templateDirty = false;
          state.templateInitial = cloneTemplate({template: result, draft: state.templateDraft});
          window.history.replaceState({}, "", "/?template=" + encodeURIComponent(result.template_id));
        };
        return;
      }
      const response = await request("/api/session");
      render(await response.json());
    }

    async function dropFlex(itemId) {
      state.armedFlexId = state.armedFlexId === itemId ? null : state.armedFlexId;
      await mutate("/api/drop", { kind: "flex", id: itemId });
    }

    async function dropDraft(itemId) {
      await mutate("/api/drop", { kind: "draft", id: itemId });
    }

    async function placeFlexAt(itemId, start) {
      clearGapHover();
      state.armedFlexId = null;
      await mutate("/api/place", { id: itemId, start: start });
    }

    async function flexToTodo(itemId) {
      await mutate("/api/convert", { kind: "flex-to-todo", id: itemId });
    }

    async function promoteChecklist(itemId, itemKind) {
      const name = window.prompt("Save this checklist to the Library as:");
      if (name === null) return;
      if (!name.trim()) {
        showSheetError("Checklist name cannot be blank.");
        return;
      }
      await mutate("/api/promote-checklist", { id: itemId, kind: itemKind, name: name });
    }

    document.getElementById("stamp-anchor").addEventListener("click", () => {
      if (state.templateMode && state.templateDraft) {
        templateEntryForm("anchor", -1);
      } else {
        sheetAddAnchor();
      }
    });
    document.getElementById("stamp-flex").addEventListener("click", () => {
      if (state.templateMode && state.templateDraft) {
        templateEntryForm("flex", -1);
      } else {
        sheetAddFlex();
      }
    });
    document.getElementById("stamp-draft").addEventListener("click", sheetAddDraft);
    document.getElementById("stamp-todo").addEventListener("click", sheetAddTodo);
    document.getElementById("wake-cap").addEventListener("click", () => sheetEditBound("wake"));
    document.getElementById("sleep-cap").addEventListener("click", () => sheetEditBound("sleep"));

    function clearGapHover(gap) {
      if (gap) {
        gap.classList.remove("hover-start", "hover-end");
        const cta = gap.querySelector(".cta");
        if (cta) {
          const isArmed = (state.armedFlexId && gap.matches("[data-kind='gap']")) ||
                          (state.templateArmedFlex && gap.matches("[data-template-gap]"));
          cta.textContent = isArmed ? "Place here" : "Place Flex";
        }
      } else {
        document.querySelectorAll(".gap.hover-start, .gap.hover-end").forEach(clearGapHover);
      }
    }

    document.getElementById("rail").addEventListener("mousemove", event => {
      const gap = event.target.closest("[data-kind='gap'], [data-template-gap]");
      if (!gap) {
        clearGapHover();
        return;
      }
      const isArmed = (state.armedFlexId && gap.matches("[data-kind='gap']")) ||
                      (state.templateArmedFlex && gap.matches("[data-template-gap]"));
      if (!isArmed) {
        clearGapHover(gap);
        return;
      }
      const rect = gap.getBoundingClientRect();
      const isBottom = rect.height > 0 && (event.clientY - rect.top) >= (rect.height / 2);
      const cta = gap.querySelector(".cta");
      if (isBottom) {
        gap.classList.remove("hover-start");
        gap.classList.add("hover-end");
        if (cta) cta.textContent = "Place at end";
      } else {
        gap.classList.remove("hover-end");
        gap.classList.add("hover-start");
        if (cta) cta.textContent = "Place at start";
      }
    });

    document.getElementById("rail").addEventListener("mouseleave", () => {
      clearGapHover();
    });

    document.getElementById("rail").addEventListener("mouseout", event => {
      const gap = event.target.closest("[data-kind='gap'], [data-template-gap]");
      if (gap && (!event.relatedTarget || !gap.contains(event.relatedTarget))) {
        clearGapHover(gap);
      }
    });

    document.getElementById("rail").addEventListener("click", event => {
      if (!state.current) return;
      const gap = event.target.closest("[data-kind='gap']");
      if (gap) {
        if (state.armedFlexId) {
          const armedFlex = (state.current.flexes || []).find(item => item.id === state.armedFlexId);
          const duration = Number(armedFlex ? (armedFlex.duration_minutes != null ? armedFlex.duration_minutes : armedFlex.duration) : 0);
          const wakeClock = state.current.bounds.wake;
          const gapDuration = gap.dataset.duration != null
            ? Number(gap.dataset.duration)
            : (toWakeMin(gap.dataset.end, wakeClock) - toWakeMin(gap.dataset.start, wakeClock));
          if (duration > gapDuration) {
            const flexName = armedFlex ? armedFlex.name : "Flex";
            showToast(`${flexName} (${fmtDur(duration)}) does not fit in this gap (${fmtDur(gapDuration)})`);
            return;
          }
          const rect = gap.getBoundingClientRect();
          const isBottom = rect.height > 0 && (event.clientY - rect.top) >= (rect.height / 2);
          if (isBottom) {
            const targetMin = toMin(gap.dataset.end) - duration;
            const computedStart = toClock(targetMin);
            placeFlexAt(state.armedFlexId, computedStart);
          } else {
            placeFlexAt(state.armedFlexId, gap.dataset.start);
          }
          return;
        }
        sheetGapPlace(gap.dataset.start, gap.dataset.end);
        return;
      }
      const block = event.target.closest("[data-kind]");
      if (!block) return;
      if (block.dataset.kind === "anchor") {
        const item = state.current.anchors.find(anchor => anchor.id === block.dataset.id);
        if (item) sheetEditAnchor(item);
        return;
      }
      if (block.dataset.kind === "flex") {
        const item = findFlex(block.dataset.id);
        if (item) sheetEditFlex(item);
      }
    });

    document.getElementById("drafts").addEventListener("click", event => {
      const dropId = event.target.dataset.dropDraft;
      if (dropId) {
        dropDraft(dropId);
        return;
      }
      const promoteId = event.target.dataset.promote;
      if (promoteId) {
        const item = findDraft(promoteId);
        if (item) sheetPromote(item);
        return;
      }
      const editId = event.target.dataset.editDraft;
      if (!editId) return;
      const item = findDraft(editId);
      if (item) sheetEditDraft(item);
    });

    document.getElementById("tray").addEventListener("click", event => {
      if (state.templateMode && state.templateDraft) {
        const actionBtn = event.target.closest("[data-template-action]");
        if (actionBtn) {
          event.stopPropagation();
          const action = actionBtn.dataset.templateAction;
          const source = actionBtn.dataset.source;
          const index = Number(actionBtn.dataset.index);
          if (action === "place") {
            if (state.templateArmedFlex && state.templateArmedFlex.source === source && state.templateArmedFlex.index === index) {
              state.templateArmedFlex = null;
            } else {
              state.templateArmedFlex = { source, index };
            }
            renderTemplateEntries();
            return;
          }
          if (action === "edit") {
            if (source === "flex") {
              const entry = state.templateDraft.flexes[index];
              templateEntryForm(entry.activity ? "activity" : "flex", index, "flex");
            } else if (source === "daily") {
              const item = state.templateDraft.dailyActivities[index];
              const entry = {
                activity: item.id,
                name: item.name,
                duration: item.duration_minutes,
                checklist: item.checklist,
                shape: "flex",
                daily: true
              };
              state.templateDraft.dailyActivities.splice(index, 1);
              state.templateDraft.flexes.push(entry);
              markTemplateDirty();
              templateEntryForm("activity", state.templateDraft.flexes.length - 1, "flex");
            }
            return;
          }
          if (action === "change-duration") {
            templateSheetChangeDuration(source, index);
            return;
          }
          if (action === "drop") {
            if (source === "flex") {
              state.templateDraft.flexes.splice(index, 1);
            } else if (source === "daily") {
              state.templateDraft.dailyActivities.splice(index, 1);
            }
            if (state.templateArmedFlex && state.templateArmedFlex.source === source && state.templateArmedFlex.index === index) {
              state.templateArmedFlex = null;
            }
            markTemplateDirty();
            renderTemplateEntries();
            return;
          }
        }
        const chip = event.target.closest("[data-template-chip]");
        if (chip) {
          event.stopPropagation();
          const source = chip.dataset.source;
          const index = Number(chip.dataset.index);
          if (state.templateArmedFlex && state.templateArmedFlex.source === source && state.templateArmedFlex.index === index) {
            state.templateArmedFlex = null;
          } else {
            state.templateArmedFlex = { source, index };
          }
          renderTemplateEntries();
          return;
        }
        return;
      }
      const dropId = event.target.dataset.drop;
      if (dropId) {
        event.stopPropagation();
        dropFlex(dropId);
        return;
      }
      const placeId = event.target.dataset.place;
      if (placeId) {
        event.stopPropagation();
        const item = findFlex(placeId);
        if (item) sheetPlace(item);
        return;
      }
      const changeDurationId = event.target.dataset.changeDuration;
      if (changeDurationId) {
        event.stopPropagation();
        const item = findFlex(changeDurationId);
        if (item) sheetChangeDuration(item);
        return;
      }
      const editId = event.target.dataset.editFlex;
      if (editId) {
        event.stopPropagation();
        const item = findFlex(editId);
        if (item) sheetEditFlex(item);
        return;
      }
      const flexToTodoId = event.target.dataset.flexToTodo;
      if (flexToTodoId) {
        event.stopPropagation();
        flexToTodo(flexToTodoId);
        return;
      }
      const chip = event.target.closest("[data-arm]");
      if (!chip) return;
      state.armedFlexId = state.armedFlexId === chip.dataset.arm ? null : chip.dataset.arm;
      if (state.current) render(state.current);
    });

    async function dropTodo(itemId) {
      await mutate("/api/drop", { kind: "todo", id: itemId });
    }

    document.getElementById("todos-tray").addEventListener("click", event => {
      const dropId = event.target.dataset.dropTodo;
      if (dropId) {
        event.stopPropagation();
        dropTodo(dropId);
        return;
      }
      const toFlexId = event.target.dataset.todoToFlex;
      if (toFlexId) {
        event.stopPropagation();
        const item = findTodo(toFlexId);
        if (item) sheetTodoToFlex(item);
        return;
      }
      const toAnchorId = event.target.dataset.todoToAnchor;
      if (toAnchorId) {
        event.stopPropagation();
        const item = findTodo(toAnchorId);
        if (item) sheetTodoToAnchor(item);
        return;
      }
      const chip = event.target.closest("[data-edit-todo]");
      if (!chip) return;
      const item = findTodo(chip.dataset.editTodo);
      if (item) sheetEditTodo(item);
    });

    document.getElementById("sheet-backdrop").addEventListener("click", event => {
      if (event.target.id === "sheet-backdrop" || event.target.dataset.close !== undefined) {
        closeSheet();
      }
    });

    document.getElementById("sheet").addEventListener("click", async event => {
      const resetField = event.target.dataset.resetField;
      if (resetField) {
        event.preventDefault();
        const form = event.target.form;
        if (resetField === "timing") {
          form.start.value = "";
          form.duration.value = "";
        } else if (resetField === "shape") {
          const option = (state.templateDraft.activityOptions || []).find(
            item => item.id === form.activity.value
          );
          form.shape.value = option && option.is_anchor_shaped ? "anchor" : "flex";
          form.start.value = "";
          form.duration.value = "";
          form.shape.dispatchEvent(new Event("change"));
        } else {
          form[resetField].value = "";
        }
        markTemplateDirty();
        return;
      }
      if (event.target.id === "template-make-flex") {
        event.preventDefault();
        const index = Number(event.target.dataset.index);
        const isActivity = event.target.dataset.activity === "true";
        if (index >= 0 && index < state.templateDraft.anchors.length) {
          const entry = state.templateDraft.anchors.splice(index, 1)[0];
          delete entry.start;
          delete entry.end;
          entry.shape = "flex";
          state.templateDraft.flexes.push(entry);
          markTemplateDirty();
          closeSheet();
          renderTemplateEntries();
        }
        return;
      }
      if (event.target.id === "template-drop-entry") {
        event.preventDefault();
        const index = Number(event.target.dataset.index);
        const kind = event.target.dataset.kind;
        const list = kind === "anchor" ? state.templateDraft.anchors : state.templateDraft.flexes;
        if (index >= 0 && index < list.length) {
          list.splice(index, 1);
          markTemplateDirty();
          closeSheet();
          renderTemplateEntries();
        }
        return;
      }
      const removeId = event.target.dataset.remove;
      if (removeId) {
        event.preventDefault();
        await mutate("/api/edit", { kind: "anchor", id: removeId, remove: true });
        return;
      }
      const dropId = event.target.dataset.drop;
      if (dropId) {
        event.preventDefault();
        await dropFlex(dropId);
        return;
      }
      const flexToTodoId = event.target.dataset.flexToTodo;
      if (flexToTodoId) {
        event.preventDefault();
        await flexToTodo(flexToTodoId);
        return;
      }
      const dropDraftId = event.target.dataset.dropDraft;
      if (dropDraftId) {
        event.preventDefault();
        await dropDraft(dropDraftId);
        return;
      }
      const dropTodoId = event.target.dataset.dropTodo;
      if (dropTodoId) {
        event.preventDefault();
        await dropTodo(dropTodoId);
        return;
      }
      const toFlexId = event.target.dataset.todoToFlex;
      if (toFlexId) {
        event.preventDefault();
        const item = findTodo(toFlexId);
        if (item) sheetTodoToFlex(item);
        return;
      }
      const toAnchorId = event.target.dataset.todoToAnchor;
      if (toAnchorId) {
        event.preventDefault();
        const item = findTodo(toAnchorId);
        if (item) sheetTodoToAnchor(item);
        return;
      }
      const placeAt = event.target.dataset.placeAt;
      if (placeAt) {
        event.preventDefault();
        await placeFlexAt(placeAt, event.target.dataset.start);
        return;
      }
      const placeId = event.target.dataset.place;
      if (placeId) {
        event.preventDefault();
        const item = findFlex(placeId);
        if (item) sheetPlace(item);
        return;
      }
      const changeDurationId = event.target.dataset.changeDuration;
      if (changeDurationId) {
        event.preventDefault();
        const item = findFlex(changeDurationId);
        if (item) sheetChangeDuration(item);
        return;
      }
      const promoteChecklistId = event.target.dataset.promoteChecklist;
      if (promoteChecklistId) {
        event.preventDefault();
        await promoteChecklist(promoteChecklistId, event.target.dataset.promoteChecklistKind);
      }
    });

    document.getElementById("rail").addEventListener("click", event => {
      if (state.templateMode && state.templateDraft) {
        const gap = event.target.closest("[data-template-gap]");
        if (gap) {
          if (state.templateArmedFlex) {
            const { source, index } = state.templateArmedFlex;
            let duration = 0;
            let flexName = "Flex";
            if (source === "flex") {
              const entry = state.templateDraft.flexes[index];
              duration = Number(entry ? (entry.duration != null ? entry.duration : entry.duration_minutes) : 0);
              flexName = entry ? (entry.name || (entry.activity ? ("Activity: " + entry.activity) : ("Flex " + (index + 1)))) : "Flex";
            } else if (source === "daily") {
              const entry = state.templateDraft.dailyActivities[index];
              duration = Number(entry ? (entry.duration_minutes != null ? entry.duration_minutes : entry.duration) : 60);
              flexName = entry ? entry.name : "Activity";
            }
            const wakeClock = state.templateDraft.bounds.wake;
            const gapDuration = gap.dataset.duration != null
              ? Number(gap.dataset.duration)
              : (toWakeMin(gap.dataset.end, wakeClock) - toWakeMin(gap.dataset.start, wakeClock));
            if (duration > gapDuration) {
              showToast(`${flexName} (${fmtDur(duration)}) does not fit in this gap (${fmtDur(gapDuration)})`);
              return;
            }
            const rect = gap.getBoundingClientRect();
            const isBottom = rect.height > 0 && (event.clientY - rect.top) >= (rect.height / 2);
            if (isBottom) {
              const targetMin = toMin(gap.dataset.end) - duration;
              const computedStart = toClock(targetMin);
              placeTemplateArmedFlex(computedStart);
            } else {
              placeTemplateArmedFlex(gap.dataset.start);
            }
          }
          return;
        }
      }
      const target = event.target.closest("[data-template-add], [data-template-entry]");
      if (!target) return;
      const addKind = target.dataset.templateAdd;
      if (addKind && state.templateDraft) {
        templateEntryForm(addKind, -1);
        return;
      }
      const kind = target.dataset.templateEntry;
      const index = target.dataset.templateIndex;
      if (kind && index !== undefined && state.templateDraft) {
        templateEntryForm(kind, Number(index), target.dataset.templateSourceKind);
      }
    });

    document.getElementById("sheet").addEventListener("input", event => {
      const form = event.target.form;
      if (!form) return;
      if (event.target.dataset.checklistSelect === "1") {
        // Attaching a Library Checklist from the select prefills the rows
        // editor with its rows, overwriting whatever was typed there.
        markTouched(form, ["checklist"]);
        if (form.checklist_items) {
          form.checklist_items.value = checklistRows(event.target.value).join("\n");
          delete form.checklist_items.dataset.touched;
        }
        return;
      }
      if (SUGGESTIBLE_FIELDS.includes(event.target.name)) {
        markTouched(form, [event.target.name]);
        if (event.target.name === "checklist_items") markTouched(form, ["checklist"]);
        return;
      }
      if (event.target.name === "name") suggestFromName(form);
    });

    document.getElementById("sheet").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.target;
      if (form.id === "add-anchor") {
        if (state.templateMode && state.templateDraft) {
          templateEntryForm("anchor", -1);
          return;
        }
        const duration = resolveDurationMinutes(form);
        if (duration === null) return;
        await mutate("/api/add", {
          kind: "anchor",
          name: form.name.value,
          start: clockValue(form.start),
          duration_minutes: duration,
          checklist: checklistPayload(form),
          checklist_items: checklistItemsPayload(form)
        });
        return;
      }
      if (form.id === "template-entry") {
        const entries = form.dataset.kind === "anchor" ? state.templateDraft.anchors : state.templateDraft.flexes;
        const duration = form.dataset.kind === "anchor"
          ? resolveDurationMinutes(form)
          : Number(form.duration_minutes.value);
        if (duration === null) return;
        const entry = form.dataset.kind === "anchor"
          ? {name: form.name.value, start: clockValue(form.start), checklist: checklistPayload(form)}
          : {name: form.name.value, checklist: checklistPayload(form)};
        if (form.dataset.kind === "anchor" && form.dataset.durationMode === "end") {
          entry.end = clockValue(form.end);
        } else {
          entry.duration = duration;
        }
        if (!duration) return;
        const index = Number(form.dataset.index);
        if (index === -1) entries.push(entry);
        else entries[index] = entry;
        markTemplateDirty();
        closeSheet();
        renderTemplateEntries();
        return;
      }
      if (form.id === "template-activity-entry") {
        const value = name => form.elements[name].value.trim();
        const entry = {
          activity: form.elements.activity.value,
          shape: form.elements.shape.value,
        };
        if (value("name")) entry.name = value("name");
        if (value("checklist")) entry.checklist = value("checklist");
        const timingTouched = form.dataset.timingTouched === "1";
        if (timingTouched) {
          if (entry.shape === "anchor" && value("start")) entry.start = value("start");
          const duration = Number(value("duration"));
          const end = value("end");
          if (entry.shape === "anchor" && value("start") && form.dataset.durationMode === "end" && end) {
            entry.end = end;
            delete entry.duration;
          } else if (duration > 0) {
            entry.duration = duration;
            delete entry.end;
          }
          if (entry.shape === "flex") {
            delete entry.start;
            delete entry.end;
          }
        }
        const entries = entry.shape === "anchor" ? state.templateDraft.anchors : state.templateDraft.flexes;
        const old = Number(form.dataset.index);
        if (old >= 0) {
          const source = form.dataset.sourceKind === "anchor" ? state.templateDraft.anchors : state.templateDraft.flexes;
          source.splice(old, 1);
        }
        entries.push(entry);
        markTemplateDirty();
        closeSheet();
        renderTemplateEntries();
        return;
      }
      if (form.id === "template-change-duration") {
        const source = form.dataset.source;
        const index = Number(form.dataset.index);
        const dur = Number(form.duration.value);
        if (dur > 0) {
          if (source === "flex") {
            state.templateDraft.flexes[index].duration = dur;
            delete state.templateDraft.flexes[index].duration_minutes;
          } else if (source === "daily") {
            const item = state.templateDraft.dailyActivities.splice(index, 1)[0];
            state.templateDraft.flexes.push({
              activity: item.id,
              name: item.name,
              duration: dur,
              checklist: item.checklist,
              shape: "flex",
              daily: true,
              timing_overridden: true
            });
          }
          markTemplateDirty();
          closeSheet();
          renderTemplateEntries();
        }
        return;
      }
      if (form.id === "add-flex") {
        if (state.templateMode && state.templateDraft) {
          templateEntryForm("flex", -1);
          return;
        }
        await mutate("/api/add", {
          kind: "flex",
          name: form.name.value,
          duration_minutes: Number(form.duration_minutes.value),
          checklist: checklistPayload(form),
          checklist_items: checklistItemsPayload(form)
        });
        return;
      }
      if (form.id === "add-draft") {
        await mutate("/api/add", {
          kind: "draft",
          name: form.name.value
        });
        return;
      }
      if (form.id === "promote-draft") {
        const payload = { id: form.dataset.id, kind: form.kind.value, name: form.name.value };
        if (form.kind.value !== "todo") {
          const duration = resolveDurationMinutes(form);
          if (duration === null) return;
          payload.duration_minutes = duration;
          payload.checklist = checklistPayload(form);
          if (form.kind.value === "anchor") payload.start = clockValue(form.start);
        }
        await mutate("/api/promote", payload);
        return;
      }
      if (form.id === "add-todo") {
        await mutate("/api/add", {
          kind: "todo",
          name: form.name.value,
          note: form.note.value
        });
        return;
      }
      if (form.id === "edit-todo") {
        await mutate("/api/edit", {
          kind: "todo",
          id: form.dataset.id,
          name: form.name.value,
          note: form.note.value
        });
        return;
      }
      if (form.id === "todo-to-flex") {
        await mutate("/api/convert", {
          kind: "todo-to-flex",
          id: form.dataset.id,
          duration_minutes: Number(form.duration_minutes.value)
        });
        return;
      }
      if (form.id === "todo-to-anchor") {
        const duration = resolveDurationMinutes(form);
        if (duration === null) return;
        await mutate("/api/convert", {
          kind: "todo-to-anchor",
          id: form.dataset.id,
          start: clockValue(form.start),
          duration_minutes: duration
        });
        return;
      }
      if (form.id === "edit-draft") {
        await mutate("/api/edit", {
          kind: "draft",
          id: form.dataset.id,
          name: form.name.value
        });
        return;
      }
      if (form.id === "place-flex") {
        await placeFlexAt(form.dataset.id, clockValue(form.start));
        return;
      }
      if (form.id === "change-duration-flex") {
        await mutate("/api/change-duration", {
          id: form.dataset.id,
          duration_minutes: Number(form.duration_minutes.value)
        });
        return;
      }
      if (form.id === "edit-anchor") {
        const duration = resolveDurationMinutes(form);
        if (duration === null) return;
        await mutate("/api/edit", {
          kind: "anchor",
          id: form.dataset.id,
          name: form.name.value,
          start: clockValue(form.start),
          duration_minutes: duration,
          checklist: checklistPayload(form),
          checklist_items: checklistItemsPayload(form)
        });
        return;
      }
      if (form.id === "edit-flex") {
        await mutate("/api/edit", {
          kind: "flex",
          id: form.dataset.id,
          name: form.name.value,
          duration_minutes: Number(form.duration_minutes.value),
          checklist: checklistPayload(form),
          checklist_items: checklistItemsPayload(form)
        });
        return;
      }
      if (form.id === "edit-bounds") {
        if (state.templateMode) {
          state.templateDraft.bounds[form.dataset.which] = clockValue(form.clock);
          renderBounds(state.templateDraft.bounds);
          markTemplateDirty();
          closeSheet();
          return;
        }
        const payload = { kind: "bounds" };
        payload[form.dataset.which] = clockValue(form.clock);
        await mutate("/api/edit", payload);
      }
    });

    function isTypingTarget(target) {
      return !!(target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA"));
    }

    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && state.sheetOpen) {
        closeSheet();
        return;
      }
      const key = event.key.toLowerCase();
      const modifier = event.metaKey || event.ctrlKey;
      if (!modifier) {
        if (state.sheetOpen) return;
        if (isTypingTarget(event.target)) return;
        if (key === "a") {
          event.preventDefault();
          if (state.templateMode && state.templateDraft) {
            templateEntryForm("anchor", -1);
          } else {
            sheetAddAnchor();
          }
        } else if (key === "f") {
          event.preventDefault();
          if (state.templateMode && state.templateDraft) {
            templateEntryForm("flex", -1);
          } else {
            sheetAddFlex();
          }
        } else if (key === "d") {
          event.preventDefault();
          sheetAddDraft();
        } else if (key === "t") {
          event.preventDefault();
          sheetAddTodo();
        }
        return;
      }
      const redo = (key === "z" && event.shiftKey) || (key === "y" && event.ctrlKey);
      if (key !== "z" && !(key === "y" && event.ctrlKey)) return;
      if (isTypingTarget(event.target) && key === "z" && !event.shiftKey) return;
      if (sessionUndoBlocked()) return;
      if (redo) {
        if (!state.current || !state.current.can_redo) return;
        event.preventDefault();
        mutate("/api/redo", {});
        return;
      }
      if (!state.current || !state.current.can_undo) return;
      event.preventDefault();
      mutate("/api/undo", {});
    });

    document.getElementById("submit").addEventListener("click", async () => {
      const blockers = (state.current && state.current.blockers) || [];
      if (blockers.length > 0) {
        flashBlockers(blockers);
        return;
      }
      const response = await request("/api/submit", { method: "POST" });
      if (response.status === 409) {
        const session = await response.json();
        render(session);
        flashBlockers(session.blockers || []);
      }
    });

    document.getElementById("reset").addEventListener("click", async () => {
      const response = await request("/api/reset", { method: "POST" });
      render(await response.json());
    });

    document.getElementById("undo").addEventListener("click", () => {
      if (sessionUndoBlocked()) return;
      mutate("/api/undo", {});
    });
    document.getElementById("redo").addEventListener("click", () => {
      if (sessionUndoBlocked()) return;
      mutate("/api/redo", {});
    });

    document.getElementById("template-yes").addEventListener("click", () => {
      mutate("/api/template", { action: "apply" });
    });
    document.getElementById("template-no").addEventListener("click", () => {
      mutate("/api/template", { action: "decline" });
    });

    const toastEl = document.getElementById("toast");
    if (toastEl) {
      toastEl.addEventListener("click", hideToast);
    }

    loadSession();
