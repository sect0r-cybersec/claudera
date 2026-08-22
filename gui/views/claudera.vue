<!--
  claudera magma GUI panel.

  Two tabs: Run History (runs grouped by MCP session, events, payload downloads)
  and Keys (issue / revoke / delete your own bearer keys). Data comes
  from the authenticated /plugin/claudera/api/* endpoints (see app/gui_api.py).
  Each user only ever sees and manages their own keys.

  The three history tables each support a page-size dropdown (10/20/50) with
  Prev/Next paging and per-column filters. Filtering and paging are done
  client-side over the rows the API already returns (runs <=100, events <=500,
  downloads <=100).

  Structure and magma/Bulma conventions are adapted from the bundled mcp plugin's
  history component (plugins/mcp/gui/views/mcp_history.vue), Apache-2.0.
  This file is part of the claudera plugin (Apache-2.0).
-->
<template>
  <div class="content" style="padding: 1.5rem;">
    <h1 class="title">Claudera</h1>
    <p class="subtitle is-6">Authenticated remote MCP server. Run history and key administration.</p>

    <div class="tabs">
      <ul>
        <li :class="{ 'is-active': tab === 'history' }"><a @click="tab = 'history'">Run history</a></li>
        <li :class="{ 'is-active': tab === 'keys' }"><a @click="tab = 'keys'">Keys</a></li>
      </ul>
    </div>
    <p class="is-size-7 has-text-grey mb-4">
      <span v-if="tab === 'history'">A record of what Claude did through the MCP server: which tools ran, who ran them, and what they created or fetched.</span>
      <span v-else>Manage the per user bearer keys that let a Claude client authenticate to this MCP server.</span>
    </p>

    <p v-if="errorMessage" class="notification is-danger is-light">{{ errorMessage }}</p>

    <!-- RUN HISTORY -->
    <div v-if="tab === 'history'">
      <!-- RUNS -->
      <div class="is-flex is-justify-content-space-between is-align-items-center mb-1">
        <h2 class="subtitle is-5 mb-0">Runs</h2>
        <button class="button is-small" @click="refreshHistory" :class="{ 'is-loading': isLoading }">Refresh</button>
      </div>
      <p class="is-size-7 has-text-grey mb-3">A run is the set of tool calls from one MCP client session, grouped by session id. Click a run to filter the events below to that session.</p>

      <div class="claudera-pager mb-2">
        <div class="claudera-pager-left">
          <span class="is-size-7 has-text-grey">Show</span>
          <div class="select is-small">
            <select v-model.number="pg.runs.size" @change="resetPage('runs')">
              <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <span class="is-size-7 has-text-grey">per page</span>
        </div>
        <div class="claudera-pager-right">
          <span class="is-size-7 has-text-grey">Page {{ pg.runs.page }} of {{ runsPages }} &middot; {{ filteredRuns.length }} rows</span>
          <button class="button is-small" :disabled="pg.runs.page <= 1" @click="pg.runs.page--">Prev</button>
          <button class="button is-small" :disabled="pg.runs.page >= runsPages" @click="pg.runs.page++">Next</button>
        </div>
      </div>

      <table class="table is-fullwidth is-striped is-narrow is-hoverable">
        <thead>
          <tr><th>Session</th><th>Started (UTC)</th><th>Last (UTC)</th><th>Users</th><th>Events</th></tr>
          <tr class="claudera-filter-row">
            <th><input class="input is-small" v-model="runFilter.session" @input="resetPage('runs')" placeholder="filter…"></th>
            <th><input class="input is-small" v-model="runFilter.started" @input="resetPage('runs')" placeholder="filter…"></th>
            <th><input class="input is-small" v-model="runFilter.last" @input="resetPage('runs')" placeholder="filter…"></th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="runFilter.users" @change="resetPage('runs')">
                  <option value="">all</option>
                  <option v-for="u in runUserOpts" :key="u" :value="u">{{ u }}</option>
                </select>
              </div>
            </th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="run in pagedRuns" :key="run.session_id"
              :class="{ 'is-selected': selectedSession === run.session_id }"
              style="cursor: pointer;" @click="selectSession(run.session_id)">
            <td><code>{{ shortId(run.session_id) }}</code></td>
            <td>{{ run.started }}</td>
            <td>{{ run.last }}</td>
            <td>{{ run.users }}</td>
            <td>{{ run.event_count }}</td>
          </tr>
          <tr v-if="!filteredRuns.length"><td colspan="5" class="has-text-grey">{{ runs.length ? 'No runs match the filters.' : 'No runs yet.' }}</td></tr>
        </tbody>
      </table>

      <!-- EVENTS -->
      <h2 class="subtitle is-5">
        Events <span v-if="selectedSession" class="tag is-info is-light">session {{ shortId(selectedSession) }}
          <button class="delete is-small ml-2" @click="selectSession(null)"></button></span>
      </h2>
      <p class="is-size-7 has-text-grey mb-3">Every tool call that changed state (create, start, pause, resume, stop, delete, download), with the tool used, the artefact affected, and the user who made it.</p>

      <div class="claudera-pager mb-2">
        <div class="claudera-pager-left">
          <span class="is-size-7 has-text-grey">Show</span>
          <div class="select is-small">
            <select v-model.number="pg.events.size" @change="resetPage('events')">
              <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <span class="is-size-7 has-text-grey">per page</span>
        </div>
        <div class="claudera-pager-right">
          <span class="is-size-7 has-text-grey">Page {{ pg.events.page }} of {{ eventsPages }} &middot; {{ filteredEvents.length }} rows</span>
          <button class="button is-small" :disabled="pg.events.page <= 1" @click="pg.events.page--">Prev</button>
          <button class="button is-small" :disabled="pg.events.page >= eventsPages" @click="pg.events.page++">Next</button>
        </div>
      </div>

      <table class="table is-fullwidth is-striped is-narrow">
        <thead>
          <tr><th>Time (UTC)</th><th>User</th><th>Tool</th><th>Artefact</th><th>Name / id</th><th>Status</th></tr>
          <tr class="claudera-filter-row">
            <th><input class="input is-small" v-model="eventFilter.ts" @input="resetPage('events')" placeholder="filter…"></th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="eventFilter.username" @change="resetPage('events')">
                  <option value="">all</option>
                  <option v-for="u in eventUserOpts" :key="u" :value="u">{{ u }}</option>
                </select>
              </div>
            </th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="eventFilter.tool" @change="resetPage('events')">
                  <option value="">all</option>
                  <option v-for="t in eventToolOpts" :key="t" :value="t">{{ t }}</option>
                </select>
              </div>
            </th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="eventFilter.artefact_type" @change="resetPage('events')">
                  <option value="">all</option>
                  <option v-for="a in eventArtefactOpts" :key="a" :value="a">{{ a }}</option>
                </select>
              </div>
            </th>
            <th><input class="input is-small" v-model="eventFilter.name" @input="resetPage('events')" placeholder="filter…"></th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="eventFilter.status" @change="resetPage('events')">
                  <option value="">all</option>
                  <option v-for="s in eventStatusOpts" :key="s" :value="s">{{ s }}</option>
                </select>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in pagedEvents" :key="e.id">
            <td>{{ e.ts }}</td><td>{{ e.username }}</td><td><code>{{ e.tool }}</code></td>
            <td>{{ e.artefact_type || '-' }}</td>
            <td>{{ e.artefact_name || e.artefact_id || '-' }}</td>
            <td><span class="tag is-light">{{ e.status || '-' }}</span></td>
          </tr>
          <tr v-if="!filteredEvents.length"><td colspan="6" class="has-text-grey">{{ events.length ? 'No events match the filters.' : 'No events.' }}</td></tr>
        </tbody>
      </table>

      <!-- PAYLOAD DOWNLOADS -->
      <h2 class="subtitle is-5">Payload downloads</h2>
      <p class="is-size-7 has-text-grey mb-3">Files fetched with download_payload, with the verified SHA-256 and whether the hash matched (ok) or was rejected (hash_mismatch). Downloads are never executed.</p>

      <div class="claudera-pager mb-2">
        <div class="claudera-pager-left">
          <span class="is-size-7 has-text-grey">Show</span>
          <div class="select is-small">
            <select v-model.number="pg.downloads.size" @change="resetPage('downloads')">
              <option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <span class="is-size-7 has-text-grey">per page</span>
        </div>
        <div class="claudera-pager-right">
          <span class="is-size-7 has-text-grey">Page {{ pg.downloads.page }} of {{ downloadsPages }} &middot; {{ filteredDownloads.length }} rows</span>
          <button class="button is-small" :disabled="pg.downloads.page <= 1" @click="pg.downloads.page--">Prev</button>
          <button class="button is-small" :disabled="pg.downloads.page >= downloadsPages" @click="pg.downloads.page++">Next</button>
        </div>
      </div>

      <table class="table is-fullwidth is-striped is-narrow">
        <thead>
          <tr><th>Time (UTC)</th><th>User</th><th>Source</th><th>Status</th><th>SHA-256</th><th>URL</th></tr>
          <tr class="claudera-filter-row">
            <th><input class="input is-small" v-model="dlFilter.ts" @input="resetPage('downloads')" placeholder="filter…"></th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="dlFilter.username" @change="resetPage('downloads')">
                  <option value="">all</option>
                  <option v-for="u in dlUserOpts" :key="u" :value="u">{{ u }}</option>
                </select>
              </div>
            </th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="dlFilter.source" @change="resetPage('downloads')">
                  <option value="">all</option>
                  <option v-for="s in dlSourceOpts" :key="s" :value="s">{{ s }}</option>
                </select>
              </div>
            </th>
            <th>
              <div class="select is-small is-fullwidth">
                <select v-model="dlFilter.status" @change="resetPage('downloads')">
                  <option value="">all</option>
                  <option v-for="s in dlStatusOpts" :key="s" :value="s">{{ s }}</option>
                </select>
              </div>
            </th>
            <th><input class="input is-small" v-model="dlFilter.sha256" @input="resetPage('downloads')" placeholder="filter…"></th>
            <th><input class="input is-small" v-model="dlFilter.url" @input="resetPage('downloads')" placeholder="filter…"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in pagedDownloads" :key="d.id">
            <td>{{ d.ts }}</td><td>{{ d.username }}</td><td>{{ d.source }}</td>
            <td><span class="tag is-light" :class="{ 'is-danger': d.status === 'hash_mismatch', 'is-success': d.status === 'ok' }">{{ d.status }}</span></td>
            <td><code>{{ (d.sha256 || '').slice(0, 16) }}</code></td>
            <td style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ d.url }}</td>
          </tr>
          <tr v-if="!filteredDownloads.length"><td colspan="6" class="has-text-grey">{{ downloads.length ? 'No downloads match the filters.' : 'No downloads.' }}</td></tr>
        </tbody>
      </table>
    </div>

    <!-- KEYS -->
    <div v-if="tab === 'keys'">
      <div class="box">
        <h2 class="subtitle is-5">Issue a key</h2>
        <p class="is-size-7 has-text-grey mb-3">Create a new bearer key for yourself. The token is shown once here, then only its hash is stored. Paste it as the Authorization Bearer value in your Claude client.</p>
        <div class="field">
          <div class="control">
            <button class="button is-primary" @click="issueKey" :class="{ 'is-loading': isBusy }">Issue a key</button>
          </div>
        </div>
        <div v-if="newToken" class="notification is-warning is-light">
          <button class="delete" @click="newToken = ''"></button>
          <strong>Copy this token now. It is shown only once:</strong>
          <pre style="white-space: pre-wrap; word-break: break-all;">{{ newToken }}</pre>
        </div>
      </div>

      <div class="is-flex is-justify-content-space-between is-align-items-center mb-1">
        <h2 class="subtitle is-5 mb-0">Keys</h2>
        <button class="button is-small" @click="fetchKeys" :class="{ 'is-loading': isLoading }">Refresh</button>
      </div>
      <p class="is-size-7 has-text-grey mb-3">Your bearer keys for this MCP server. Revoke disables a key permanently — a revoked key cannot be turned back on and can only be deleted. Delete removes the key for good (and revokes it in the same step). To replace a key, revoke or delete the old one and issue a new key.</p>
      <table class="table is-fullwidth is-striped is-narrow is-hoverable">
        <thead>
          <tr><th>Key id</th><th>User</th><th>Group</th><th>Active</th><th>Created (UTC)</th><th>Last used</th><th>Actions</th></tr>
        </thead>
        <tbody>
          <tr v-for="k in keys" :key="k.key_id">
            <td><code>{{ k.key_id }}</code></td><td>{{ k.username }}</td><td>{{ k.group }}</td>
            <td><span class="tag" :class="k.active ? 'is-success' : 'is-danger'">{{ k.active ? 'active' : 'revoked' }}</span></td>
            <td>{{ k.created_at }}</td><td>{{ k.last_used_at || '-' }}</td>
            <td>
              <button v-if="k.active" class="button is-small is-danger is-light mr-1" @click="revokeKey(k.key_id)">Revoke</button>
              <button class="button is-small is-danger" @click="deleteKey(k.key_id)">Delete</button>
            </td>
          </tr>
          <tr v-if="!keys.length"><td colspan="7" class="has-text-grey">No keys.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { inject, ref, reactive, computed, onMounted } from "vue";

const $api = inject("$api");

const tab = ref("history");
const errorMessage = ref("");
const isLoading = ref(false);
const isBusy = ref(false);

const runs = ref([]);
const events = ref([]);
const downloads = ref([]);
const selectedSession = ref(null);

const keys = ref([]);
const newToken = ref("");

// -- paging + filtering (history tables) ------------------------------------

const PAGE_SIZES = [10, 20, 50];

// Per-table page size + current page.
const pg = reactive({
  runs: { size: 10, page: 1 },
  events: { size: 10, page: 1 },
  downloads: { size: 10, page: 1 },
});

// Per-column filters. Text fields use substring match; the rest are dropdowns
// (exact match, blank = all).
const runFilter = reactive({ session: "", started: "", last: "", users: "" });
const eventFilter = reactive({ ts: "", username: "", tool: "", artefact_type: "", name: "", status: "" });
const dlFilter = reactive({ ts: "", username: "", source: "", status: "", sha256: "", url: "" });

function inc(cell, q) {
  if (!q) return true;
  return String(cell ?? "").toLowerCase().includes(String(q).toLowerCase());
}
function eq(cell, q) {
  if (!q) return true;
  return String(cell ?? "") === String(q);
}
function distinct(rows, key) {
  return [...new Set(rows.map((r) => String(r[key] ?? "")).filter((v) => v !== ""))].sort();
}

// Dropdown option sources (recomputed from the loaded rows).
const runUserOpts = computed(() => distinct(runs.value, "users"));
const eventUserOpts = computed(() => distinct(events.value, "username"));
const eventToolOpts = computed(() => distinct(events.value, "tool"));
const eventArtefactOpts = computed(() => distinct(events.value, "artefact_type"));
const eventStatusOpts = computed(() => distinct(events.value, "status"));
const dlUserOpts = computed(() => distinct(downloads.value, "username"));
const dlSourceOpts = computed(() => distinct(downloads.value, "source"));
const dlStatusOpts = computed(() => distinct(downloads.value, "status"));

// Filtered lists (AND across columns).
const filteredRuns = computed(() =>
  runs.value.filter(
    (r) =>
      inc(r.session_id, runFilter.session) &&
      inc(r.started, runFilter.started) &&
      inc(r.last, runFilter.last) &&
      eq(r.users, runFilter.users)
  )
);
const filteredEvents = computed(() =>
  events.value.filter(
    (e) =>
      inc(e.ts, eventFilter.ts) &&
      eq(e.username, eventFilter.username) &&
      eq(e.tool, eventFilter.tool) &&
      eq(e.artefact_type, eventFilter.artefact_type) &&
      inc(e.artefact_name || e.artefact_id, eventFilter.name) &&
      eq(e.status, eventFilter.status)
  )
);
const filteredDownloads = computed(() =>
  downloads.value.filter(
    (d) =>
      inc(d.ts, dlFilter.ts) &&
      eq(d.username, dlFilter.username) &&
      eq(d.source, dlFilter.source) &&
      eq(d.status, dlFilter.status) &&
      inc(d.sha256, dlFilter.sha256) &&
      inc(d.url, dlFilter.url)
  )
);

function pageCount(list, st) {
  return Math.max(1, Math.ceil(list.length / st.size));
}
const runsPages = computed(() => pageCount(filteredRuns.value, pg.runs));
const eventsPages = computed(() => pageCount(filteredEvents.value, pg.events));
const downloadsPages = computed(() => pageCount(filteredDownloads.value, pg.downloads));

function slicePage(list, st, pages) {
  const page = Math.min(st.page, pages); // clamp so a shrunk list never shows an empty page
  const start = (page - 1) * st.size;
  return list.slice(start, start + st.size);
}
const pagedRuns = computed(() => slicePage(filteredRuns.value, pg.runs, runsPages.value));
const pagedEvents = computed(() => slicePage(filteredEvents.value, pg.events, eventsPages.value));
const pagedDownloads = computed(() => slicePage(filteredDownloads.value, pg.downloads, downloadsPages.value));

function resetPage(name) {
  pg[name].page = 1;
}

// -- data loading ----------------------------------------------------------

function shortId(id) {
  return id ? String(id).slice(0, 8) : "-";
}

function fail(err, fallback) {
  errorMessage.value = err?.response?.data?.error || fallback;
}

async function refreshHistory() {
  isLoading.value = true;
  errorMessage.value = "";
  try {
    const [r, d] = await Promise.all([
      $api.get("/plugin/claudera/api/runs"),
      $api.get("/plugin/claudera/api/downloads"),
    ]);
    runs.value = r.data || [];
    downloads.value = d.data || [];
    resetPage("runs");
    resetPage("downloads");
    await fetchEvents();
  } catch (err) {
    fail(err, "Failed to load run history.");
  } finally {
    isLoading.value = false;
  }
}

async function fetchEvents() {
  try {
    const params = selectedSession.value ? { session_id: selectedSession.value } : {};
    const res = await $api.get("/plugin/claudera/api/events", { params });
    events.value = res.data || [];
    resetPage("events");
  } catch (err) {
    fail(err, "Failed to load events.");
  }
}

function selectSession(id) {
  selectedSession.value = id;
  fetchEvents();
}

async function fetchKeys() {
  isLoading.value = true;
  errorMessage.value = "";
  try {
    const res = await $api.get("/plugin/claudera/api/keys");
    keys.value = res.data || [];
  } catch (err) {
    fail(err, "Failed to load keys.");
  } finally {
    isLoading.value = false;
  }
}

async function issueKey() {
  isBusy.value = true;
  errorMessage.value = "";
  newToken.value = "";
  try {
    const res = await $api.post("/plugin/claudera/api/keys/issue", {});
    newToken.value = res.data.token;
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to issue key.");
  } finally {
    isBusy.value = false;
  }
}

async function revokeKey(keyId) {
  if (!window.confirm("Revoke this key? This is permanent — a revoked key cannot be reactivated, only deleted.")) return;
  try {
    await $api.post("/plugin/claudera/api/keys/revoke", { key_id: keyId });
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to revoke key.");
  }
}

async function deleteKey(keyId) {
  if (!window.confirm("Delete this key permanently? Any Claude client still using it will stop working.")) return;
  try {
    await $api.post("/plugin/claudera/api/keys/delete", { key_id: keyId });
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to delete key.");
  }
}

onMounted(() => {
  refreshHistory();
  fetchKeys();
});
</script>

<style scoped>
.claudera-pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.claudera-pager-left,
.claudera-pager-right {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.claudera-filter-row th {
  padding: 0.25rem 0.4rem;
}
.claudera-filter-row .input,
.claudera-filter-row .select select {
  font-size: 0.75rem;
}
</style>
