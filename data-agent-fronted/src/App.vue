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

          <!-- 表格 -->
          <div v-else-if="msg.type === 'table'" class="table-wrap">
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

function toggleSteps(msg) {
  msg.collapsed = !msg.collapsed;
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

        // ✅ 表格结果：兼容 type=result、直接数组、以及常见包裹字段
        else if (
            (typeof data === "object" && data?.type === "result") ||
            Array.isArray(data) ||
            (typeof data === "object" && data !== null)
        ) {
          const rows = extractTableRows(data);
          if (!rows) continue;
          hasFinalResult = true;
          messages.value.push({
            role: "assistant",
            type: "table",
            columns: Object.keys(rows[0] || {}),
            rows,
          });
        }

        // ✅ 错误
        else if (typeof data === "object" && data?.type === "error") {
          messages.value.push({
            role: "assistant",
            type: "error",
            content: data.message || "发生错误",
          });
        }

        await nextTick();
        scrollToBottom();
      }
    }

    if (!hasFinalResult) {
      messages.value.push({
        role: "assistant",
        type: "error",
        content: "流程已完成，但后端未返回最终结果数据（表格行）。",
      });
    }
  } catch (e) {
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

/* 表格 */
.table-wrap {
  max-width: 100%;
  overflow-x: auto;
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
