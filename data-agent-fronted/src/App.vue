<template>
  <div class="chat-page">
    <!-- 消息区 -->
    <div ref="messagesEl" class="messages">
      <div
          v-for="(msg, index) in messages"
          :key="index"
          :class="['message-row', msg.role]"
      >
        <div v-if="msg.role === 'assistant'" class="avatar">🤖</div>

        <div class="bubble">
          <!-- 文本 -->
          <div v-if="msg.type === 'text'">
            {{ msg.content }}
          </div>

          <!-- 进度步骤 -->
          <div v-else-if="msg.type === 'steps'" class="steps">
            <button
                class="thinking-header"
                type="button"
                @click="toggleSteps(msg)"
            >
              <span
                  v-if="loading && index === messages.length - 1"
                  class="thinking-spinner"
              ></span>
              <span class="thinking-text">
                {{ loading && index === messages.length - 1 ? "正在思考..." : "已完成思考" }}
              </span>
              <span class="thinking-toggle">
                {{ msg.collapsed ? "展开" : "收起" }}
              </span>
            </button>

            <div
                v-show="!msg.collapsed"
                v-for="(step, sIdx) in msg.steps"
                :key="sIdx"
                :class="[
                'step',
                {
                  active: step.status === 'running',
                  done: step.status === 'success',
                  failed: step.status === 'error',
                },
              ]"
            >
              <span class="dot" :class="step.status"></span>
              <span>{{ step.text }}</span>
            </div>
          </div>

          <!-- 节点轨迹 -->
          <div v-else-if="msg.type === 'trace-node'" class="trace-node">
            <button class="trace-header" type="button" @click="toggleTrace(msg)">
              <span class="trace-title">{{ msg.title || msg.node }}</span>
              <span :class="['trace-state', msg.status]">{{ telemetryStatusLabel(msg.status) }}</span>
              <span v-if="msg.durationMs !== undefined" class="trace-duration">{{ msg.durationMs }} ms</span>
              <span class="trace-toggle">{{ msg.collapsed ? "展开" : "收起" }}</span>
            </button>
            <pre v-show="!msg.collapsed && msg.content" class="trace-content">{{ msg.content }}</pre>
          </div>

          <!-- 表格 -->
          <div v-else-if="msg.type === 'table'" class="table-wrap">
            <div v-if="msg.sql || msg.meta" class="result-meta">
              <div class="result-stats">
                <span v-if="msg.meta?.rowCount !== undefined">行数：{{ msg.meta.rowCount }}</span>
                <span v-if="msg.meta?.correctionAttempts !== undefined">
                  纠错：{{ msg.meta.correctionAttempts }} 次
                </span>
                <span v-if="msg.meta?.elapsedMs !== undefined">耗时：{{ msg.meta.elapsedMs }} ms</span>
              </div>
              <pre v-if="msg.sql" class="sql-details">{{ msg.sql }}</pre>
            </div>
            <table class="result-table">
              <thead>
              <tr>
                <th v-for="col in msg.columns" :key="col">
                  {{ col }}
                </th>
              </tr>
              </thead>
              <tbody>
              <tr v-for="(row, rIdx) in msg.rows" :key="rIdx">
                <td v-for="col in msg.columns" :key="col">
                  {{ row[col] }}
                </td>
              </tr>
              </tbody>
            </table>
            <div v-if="msg.rows.length === 0" class="empty-result">暂无数据</div>
          </div>

          <!-- 诊断 -->
          <div v-else-if="msg.type === 'diagnostics'" class="diagnostics">
            <div class="diagnostics-title">节点运行状态</div>
            <div
                v-for="(item, dIdx) in msg.items"
                :key="dIdx"
                :class="['diagnostic-item', item.status]"
            >
              <span class="diagnostic-node">{{ item.title || item.node }}</span>
              <span class="diagnostic-state">{{ telemetryStatusLabel(item.status) }}</span>
              <span class="diagnostic-duration">
                {{ item.durationMs !== undefined ? `${item.durationMs} ms` : '...' }}
              </span>
              <pre v-if="item.content" class="diagnostic-content">{{ item.content }}</pre>
            </div>
          </div>

          <!-- 错误 -->
          <div v-else-if="msg.type === 'error'" class="error-text">
            {{ msg.content }}
          </div>
        </div>

        <div v-if="msg.role === 'user'" class="avatar">🧑</div>
      </div>
      <div class="messages-bottom-spacer"></div>
    </div>

    <!-- 悬浮输入框 -->
    <div class="input-wrapper">
      <div class="input-box">
        <input
            v-model="question"
            @keyup.enter="sendQuestion"
            placeholder="请输入你的问题..."
        />
        <button @click="sendQuestion" :disabled="loading">
          {{ loading ? "执行中..." : "发送" }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import {nextTick, ref} from "vue";

const API_URL = "/api/query";

const question = ref("");
const loading = ref(false);
const messages = ref([]);
const messagesEl = ref(null);

function scrollToBottom() {
  const el = messagesEl.value;
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}

function extractTableRows(data) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== "object") return null;

  const candidates = [data.data, data.list, data.result, data.rows];
  for (const item of candidates) {
    if (Array.isArray(item)) return item;
  }
  return null;
}

function telemetryStatusLabel(status) {
  if (status === "running") return "运行中";
  if (status === "success") return "已完成";
  if (status === "error") return "失败";
  return status || "未知";
}

function normalizeTraceEvent(data) {
  return {
    id: data.id || data.node,
    node: data.node,
    title: data.title || data.node,
    status: data.status || "running",
    durationMs: data.duration_ms,
    metrics: data.metrics || {},
    content: data.content,
    delta: data.delta,
    event: data.event || data.phase,
  };
}

function normalizeResultMeta(data, rows, requestStartedAt) {
  if (!data || typeof data !== "object") {
    return {
      rowCount: rows.length,
      elapsedMs: Math.round(performance.now() - requestStartedAt),
    };
  }

  return {
    rowCount: data.meta?.row_count ?? rows.length,
    correctionAttempts: data.correction_attempts ?? data.meta?.correction_attempts,
    elapsedMs: Math.round(performance.now() - requestStartedAt),
  };
}

function toggleSteps(msg) {
  msg.collapsed = !msg.collapsed;
}

function toggleTrace(msg) {
  msg.collapsed = !msg.collapsed;
}

function collapseTraceMessages() {
  for (const msg of messages.value) {
    if (msg.type === "trace-node") {
      msg.collapsed = true;
    }
  }
}

async function sendQuestion() {
  if (!question.value || loading.value) return;

  const q = question.value;
  question.value = "";
  loading.value = true;

  messages.value.push({role: "user", type: "text", content: q});

  // steps 容器
  const stepIndex =
      messages.value.push({
        role: "assistant",
        type: "steps",
        steps: [],
        collapsed: true,
      }) - 1;

  await nextTick();
  scrollToBottom();

  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({query: q}),
    });

    if (!response.body) throw new Error("服务器未返回流");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    let hasFinalResult = false;
    let requestStartedAt = performance.now();
    const traceMessageIndexes = new Map();

    while (true) {
      const {value, done} = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, {stream: true});
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const evt of events) {
        // SSE 一个事件里可能有多行，这里只抽取 data: 行并拼接
        const dataLines = evt
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.replace(/^data:\s*/, ""));

        if (dataLines.length === 0) continue;
        const payload = dataLines.join("\n");

        let data;
        try {
          data = JSON.parse(payload);
        } catch {
          data = payload;
        }

        const steps = messages.value[stepIndex].steps;

        // ✅ progress：完全按后端状态渲染
        if (typeof data === "object" && data?.type === "progress") {
          let step = steps.find((s) => s.text === data.step);

          if (!step) {
            step = {
              text: data.step,
              status: data.status,
            };
            steps.push(step);
          } else {
            step.status = data.status;
          }
        }

        // ✅ 纯文本进度（后端返回 data: "抽取关键词" 这种格式）
        else if (typeof data === "string") {
          steps.push({
            text: data,
            status: "success",
          });
        }

        // trace：一个节点一个对话气泡，并支持增量内容
        else if (typeof data === "object" && data?.type === "trace") {
          const trace = normalizeTraceEvent(data);
          let traceIndex = traceMessageIndexes.get(trace.id);

          if (traceIndex === undefined) {
            traceIndex = messages.value.push({
              role: "assistant",
              type: "trace-node",
              id: trace.id,
              node: trace.node,
              title: trace.title,
              status: trace.status,
              durationMs: trace.durationMs,
              metrics: trace.metrics,
              content: "",
              hasDelta: false,
              collapsed: false,
            }) - 1;
            traceMessageIndexes.set(trace.id, traceIndex);
          }

          const traceMessage = messages.value[traceIndex];
          traceMessage.node = trace.node || traceMessage.node;
          traceMessage.title = trace.title || traceMessage.title;
          traceMessage.status = trace.status || traceMessage.status;
          traceMessage.metrics = trace.metrics || traceMessage.metrics;
          if (trace.durationMs !== undefined) {
            traceMessage.durationMs = trace.durationMs;
          }

          if (trace.delta) {
            if (traceMessage.content && !traceMessage.hasDelta) {
              traceMessage.content = `${traceMessage.content}\n`;
            }
            traceMessage.content = `${traceMessage.content || ""}${trace.delta}`;
            traceMessage.hasDelta = true;
          } else if (trace.content) {
            if (trace.event === "node_start" && !traceMessage.content) {
              traceMessage.content = trace.content;
            } else if (!traceMessage.hasDelta && !traceMessage.content.includes(trace.content)) {
              traceMessage.content = traceMessage.content
                  ? `${traceMessage.content}\n${trace.content}`
                  : trace.content;
            }
          }
        }

        // 错误事件必须早于通用 object 结果分支
        else if (typeof data === "object" && data?.type === "error") {
          hasFinalResult = true;
          collapseTraceMessages();
          messages.value.push({
            role: "assistant",
            type: "error",
            content: data.message || data.error || "发生错误",
          });
        }

        // ✅ 表格结果：兼容 type=result、直接数组、以及常见包裹字段
        else if (
            (typeof data === "object" && data?.type === "result") ||
            Array.isArray(data) ||
            (typeof data === "object" && data !== null)
        ) {
          const rows = extractTableRows(data);
          if (!rows) continue;
          hasFinalResult = true;
          collapseTraceMessages();
          messages.value.push({
            role: "assistant",
            type: "table",
            columns: Object.keys(rows[0] || {}),
            rows,
          });


        }

        await nextTick();
        scrollToBottom();
      }
    }

    if (!hasFinalResult) {
      collapseTraceMessages();
      messages.value.push({
        role: "assistant",
        type: "error",
        content: "流程已完成，但后端未返回最终结果数据（表格行）。",
      });
    }
  } catch (e) {
    collapseTraceMessages();
    messages.value.push({
      role: "assistant",
      type: "error",
      content: e?.message || "请求失败",
    });
  } finally {
    loading.value = false;
    await nextTick();
    scrollToBottom();
  }
}
</script>
<style scoped>
/* 覆盖 Vite 默认居中 */
:global(html),
:global(body) {
  height: 100%;
  margin: 0;
}

:global(body) {
  display: block !important;
  place-items: unset !important;
}

:global(#app) {
  height: 100%;
  max-width: none !important;
  margin: 0 !important;
  padding: 0 !important;
}

/* 页面 */
.chat-page {
  height: 100%;
  overflow: hidden;
  background: #fff;
}

/* 消息区 */
.messages {
  height: 100%;
  overflow-y: auto;
  padding: 20px 20% 160px;
}

.message-row {
  display: flex;
  margin-bottom: 14px;
}

.message-row.assistant {
  justify-content: flex-start;
}

.message-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 10px;
}

.bubble {
  max-width: min(820px, 72%);
  padding: 12px 14px;
  border-radius: 12px;
  background: #f5f5f5;
}

.message-row.user .bubble {
  background: #e6f4ff;
}

/* 步骤 */
.steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 2px 2px 4px;
}

.thinking-header {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
  margin-bottom: 2px;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  outline: none;
  box-shadow: none;
  appearance: none;
  -webkit-appearance: none;
}

.thinking-header:hover,
.thinking-header:focus,
.thinking-header:focus-visible,
.thinking-header:active {
  border: none;
  outline: none;
  box-shadow: none;
}

.thinking-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #dbeafe;
  border-top-color: #409eff;
  animation: spin 0.9s linear infinite;
}

.thinking-text {
  letter-spacing: 0.2px;
}

.thinking-toggle {
  color: #2563eb;
  font-size: 12px;
}

.step {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  line-height: 1.35;
  transition: all 0.2s ease;
}

.step.active {
  color: #0f172a;
  font-weight: 600;
}

.step.done {
  color: #1f2937;
}

.step.failed {
  color: #b42318;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #cbd5e1;
  flex: 0 0 10px;
  box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.03);
}

.dot.running {
  background: #409eff;
  animation: pulse 1.1s ease-in-out infinite;
}

.dot.success {
  background: #34c759;
}

.dot.error {
  background: #f04438;
}

@keyframes pulse {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(64, 158, 255, 0.45);
  }
  70% {
    transform: scale(1);
    box-shadow: 0 0 0 8px rgba(64, 158, 255, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(64, 158, 255, 0);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* 节点轨迹 */
.trace-node {
  min-width: 260px;
  max-width: 100%;
}

.trace-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 8px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.trace-title {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-state {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2f7;
  color: #475569;
  font-size: 12px;
}

.trace-state.running {
  background: #dbeafe;
  color: #1d4ed8;
}

.trace-state.success {
  background: #dcfce7;
  color: #15803d;
}

.trace-state.error {
  background: #fee2e2;
  color: #b42318;
}

.trace-duration {
  flex: 0 0 auto;
  color: #64748b;
  font-size: 12px;
}

.trace-toggle {
  flex: 0 0 auto;
  color: #2563eb;
  font-size: 12px;
}

.trace-content {
  max-height: 220px;
  margin: 0;
  padding: 8px 10px;
  overflow: auto;
  border-left: 2px solid #bfdbfe;
  border-radius: 6px;
  background: #f8fafc;
  color: #334155;
  font-family: Consolas, Monaco, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 表格 */
.table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.result-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.result-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: #475569;
  font-size: 12px;
}

.result-stats span {
  padding: 2px 7px;
  border-radius: 6px;
  background: #eef2f7;
}

.sql-details {
  max-width: 100%;
  margin: 0;
  padding: 8px 10px;
  overflow-x: auto;
  border-radius: 6px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.result-table {
  width: max-content;
  min-width: 100%;
  table-layout: auto;
  border-collapse: collapse;
}

.result-table th,
.result-table td {
  border: 1px solid #ddd;
  padding: 6px 12px;
  white-space: nowrap;
  font-size: 13px;
  text-align: left;
}

.result-table th {
  background: #fafafa;
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}

.empty-result {
  margin-top: 8px;
  color: #64748b;
  font-size: 13px;
}

.diagnostics {
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.diagnostics-title {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.diagnostic-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px 12px;
  align-items: center;
  color: #475569;
  font-size: 12px;
}

.diagnostic-node {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.diagnostic-state {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2f7;
}

.diagnostic-duration {
  color: #64748b;
}

.diagnostic-content {
  grid-column: 1 / -1;
  max-height: 180px;
  margin: 2px 0 0;
  padding: 8px 10px;
  overflow: auto;
  border-left: 2px solid #bfdbfe;
  border-radius: 6px;
  background: #f8fafc;
  color: #334155;
  font-family: Consolas, Monaco, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.diagnostic-item.running .diagnostic-state {
  background: #dbeafe;
  color: #1d4ed8;
}

.diagnostic-item.success .diagnostic-state {
  background: #dcfce7;
  color: #15803d;
}

.diagnostic-item.error .diagnostic-state {
  background: #fee2e2;
  color: #b42318;
}

/* 错误 */
.error-text {
  color: #e74c3c;
  font-weight: 600;
}

/* 悬浮输入框 */
.input-wrapper {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 24px;
  display: flex;
  justify-content: center;
  padding: 0 16px;
  pointer-events: none;
}

.input-box {
  pointer-events: auto;
  width: 100%;
  max-width: 720px;
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.12);
}

.input-box input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
}

.input-box button {
  padding: 8px 18px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: #fff;
  cursor: pointer;
}

.input-box button:disabled {
  opacity: 0.5;
}

.messages-bottom-spacer {
  height: 200px;
}
</style>
