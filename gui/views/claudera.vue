<!--
  claudera magma GUI panel.

  Two tabs: Run History (runs grouped by MCP session, events, payload downloads)
  and Keys (issue / rotate / revoke per-user bearer keys). Data comes from the
  authenticated /plugin/claudera/api/* endpoints (see app/gui_api.py).

  Structure and magma/Bulma conventions are adapted from the bundled mcp plugin's
  history component (plugins/mcp/gui/views/mcp_history.vue), Apache-2.0.
  This file is part of the claudera plugin (Apache-2.0).
-->
<template>
  <div class="content" style="padding: 1.5rem;">
    <h1 class="title">claudera</h1>
    <p class="subtitle is-6">Authenticated remote MCP server &mdash; run history &amp; key administration</p>

    <div class="tabs">
      <ul>
        <li :class="{ 'is-active': tab === 'history' }"><a @click="tab = 'history'">Run history</a></li>
        <li :class="{ 'is-active': tab === 'keys' }"><a @click="tab = 'keys'">Keys</a></li>
      </ul>
    </div>

    <p v-if="errorMessage" class="notification is-danger is-light">{{ errorMessage }}</p>

    <!-- RUN HISTORY -->
    <div v-if="tab === 'history'">
      <div class="is-flex is-justify-content-space-between is-align-items-center mb-3">
        <h2 class="subtitle is-5 mb-0">Runs</h2>
        <button class="button is-small" @click="refreshHistory" :class="{ 'is-loading': isLoading }">Refresh</button>
      </div>
      <table class="table is-fullwidth is-striped is-narrow is-hoverable">
        <thead>
          <tr><th>Session</th><th>Started (UTC)</th><th>Last (UTC)</th><th>Users</th><th>Events</th></tr>
        </thead>
        <tbody>
          <tr v-for="run in runs" :key="run.session_id"
              :class="{ 'is-selected': selectedSession === run.session_id }"
              style="cursor: pointer;" @click="selectSession(run.session_id)">
            <td><code>{{ shortId(run.session_id) }}</code></td>
            <td>{{ run.started }}</td>
            <td>{{ run.last }}</td>
            <td>{{ run.users }}</td>
            <td>{{ run.event_count }}</td>
          </tr>
          <tr v-if="!runs.length"><td colspan="5" class="has-text-grey">No runs yet.</td></tr>
        </tbody>
      </table>

      <h2 class="subtitle is-5">
        Events <span v-if="selectedSession" class="tag is-info is-light">session {{ shortId(selectedSession) }}
          <button class="delete is-small ml-2" @click="selectSession(null)"></button></span>
      </h2>
      <table class="table is-fullwidth is-striped is-narrow">
        <thead>
          <tr><th>Time (UTC)</th><th>User</th><th>Tool</th><th>Artefact</th><th>Name / id</th><th>Status</th></tr>
        </thead>
        <tbody>
          <tr v-for="(e, i) in events" :key="i">
            <td>{{ e.ts }}</td><td>{{ e.username }}</td><td><code>{{ e.tool }}</code></td>
            <td>{{ e.artefact_type || '-' }}</td>
            <td>{{ e.artefact_name || e.artefact_id || '-' }}</td>
            <td><span class="tag is-light">{{ e.status || '-' }}</span></td>
          </tr>
          <tr v-if="!events.length"><td colspan="6" class="has-text-grey">No events.</td></tr>
        </tbody>
      </table>

      <h2 class="subtitle is-5">Payload downloads</h2>
      <table class="table is-fullwidth is-striped is-narrow">
        <thead>
          <tr><th>Time (UTC)</th><th>User</th><th>Source</th><th>Status</th><th>SHA-256</th><th>URL</th></tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in downloads" :key="i">
            <td>{{ d.ts }}</td><td>{{ d.username }}</td><td>{{ d.source }}</td>
            <td><span class="tag is-light" :class="{ 'is-danger': d.status === 'hash_mismatch', 'is-success': d.status === 'ok' }">{{ d.status }}</span></td>
            <td><code>{{ (d.sha256 || '').slice(0, 16) }}</code></td>
            <td style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ d.url }}</td>
          </tr>
          <tr v-if="!downloads.length"><td colspan="6" class="has-text-grey">No downloads.</td></tr>
        </tbody>
      </table>
    </div>

    <!-- KEYS -->
    <div v-if="tab === 'keys'">
      <div class="box">
        <h2 class="subtitle is-5">Issue a key</h2>
        <div class="field has-addons">
          <div class="control">
            <input class="input" type="text" v-model="issueUsername"
                   placeholder="username (blank = yourself)">
          </div>
          <div class="control">
            <button class="button is-primary" @click="issueKey" :class="{ 'is-loading': isBusy }">Issue</button>
          </div>
        </div>
        <div v-if="newToken" class="notification is-warning is-light">
          <button class="delete" @click="newToken = ''"></button>
          <strong>Copy this token now &mdash; it is shown only once:</strong>
          <pre style="white-space: pre-wrap; word-break: break-all;">{{ newToken }}</pre>
        </div>
      </div>

      <div class="is-flex is-justify-content-space-between is-align-items-center mb-3">
        <h2 class="subtitle is-5 mb-0">Keys</h2>
        <button class="button is-small" @click="fetchKeys" :class="{ 'is-loading': isLoading }">Refresh</button>
      </div>
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
              <button class="button is-small mr-1" @click="rotateKey(k.key_id)">Rotate</button>
              <button v-if="k.active" class="button is-small is-danger is-light" @click="revokeKey(k.key_id)">Revoke</button>
              <button v-else class="button is-small is-success is-light" @click="activateKey(k.key_id)">Activate</button>
            </td>
          </tr>
          <tr v-if="!keys.length"><td colspan="7" class="has-text-grey">No keys.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { inject, ref, onMounted } from "vue";

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
const issueUsername = ref("");
const newToken = ref("");

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
    const body = issueUsername.value ? { username: issueUsername.value } : {};
    const res = await $api.post("/plugin/claudera/api/keys/issue", body);
    newToken.value = res.data.token;
    issueUsername.value = "";
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to issue key.");
  } finally {
    isBusy.value = false;
  }
}

async function rotateKey(keyId) {
  errorMessage.value = "";
  try {
    const res = await $api.post("/plugin/claudera/api/keys/rotate", { key_id: keyId });
    newToken.value = res.data.token;
    tab.value = "keys";
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to rotate key.");
  }
}

async function revokeKey(keyId) {
  try {
    await $api.post("/plugin/claudera/api/keys/revoke", { key_id: keyId });
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to revoke key.");
  }
}

async function activateKey(keyId) {
  try {
    await $api.post("/plugin/claudera/api/keys/activate", { key_id: keyId });
    await fetchKeys();
  } catch (err) {
    fail(err, "Failed to activate key.");
  }
}

onMounted(() => {
  refreshHistory();
  fetchKeys();
});
</script>
