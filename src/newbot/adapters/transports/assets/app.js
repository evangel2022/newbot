"use strict";

const capabilities = document.getElementById("capabilities");
const transcript = document.getElementById("transcript");
const tokenInput = document.getElementById("token");
const conversationInput = document.getElementById("conversation");

function append(line) {
  transcript.textContent += line;
  transcript.scrollTop = transcript.scrollHeight;
}

async function loadCapabilities() {
  const response = await fetch("/capabilities");
  const info = await response.json();
  capabilities.textContent =
    "protocol " + info.protocol + " / " + info.capabilities.join(", ");
}

async function connectStream() {
  const response = await fetch("/ticket", {
    method: "POST",
    headers: { Authorization: "Bearer " + tokenInput.value },
  });
  if (!response.ok) {
    append("\nstream: HTTP " + response.status + "\n");
    return;
  }
  const body = await response.json();
  const socket = new WebSocket("ws://" + location.host + "/stream", [
    "newbot.ticket." + body.ticket,
  ]);
  socket.addEventListener("message", (event) => {
    const frame = JSON.parse(event.data);
    if (frame.type === "delta") append(frame.text);
    else if (frame.type === "error") append("\n" + frame.message + "\n");
  });
  socket.addEventListener("close", () => append("\nstream closed\n"));
}

async function sendTurn(text) {
  const response = await fetch("/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + tokenInput.value,
    },
    body: JSON.stringify({
      conversation: conversationInput.value || "default",
      text,
    }),
  });
  const body = await response.json();
  append("bot: " + (body.reply !== undefined ? body.reply : body.error) + "\n");
}

document.getElementById("connect").addEventListener("click", connectStream);
document.getElementById("compose").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("message");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  append("you: " + text + "\n");
  sendTurn(text);
});

loadCapabilities();
