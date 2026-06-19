(function () {
  const uploadForm = document.querySelector("#upload-form");
  const taskShell = document.querySelector(".task-shell");

  if (uploadForm) {
    setupUpload(uploadForm);
  }

  if (taskShell) {
    setupTaskPage(taskShell);
  }

  function setupUpload(form) {
    const fileInput = document.querySelector("#video-file");
    const languageInput = document.querySelector("#language");
    const submitButton = document.querySelector("#submit-button");
    const statusLine = document.querySelector("#upload-status");
    const config = window.VideoClipperConfig || {};

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const file = fileInput.files[0];
      if (!file) {
        setStatus(statusLine, "请选择视频文件。", true);
        return;
      }

      const dotIndex = file.name.lastIndexOf(".");
      const extension = dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : "";
      if (config.allowedExtensions && !config.allowedExtensions.includes(extension)) {
        setStatus(statusLine, "不支持的视频格式。", true);
        return;
      }

      if (config.maxUploadBytes && file.size > config.maxUploadBytes) {
        setStatus(statusLine, "文件超过大小限制。", true);
        return;
      }

      const formData = new FormData();
      formData.append("file", file);
      formData.append("language", languageInput.value);

      submitButton.disabled = true;
      setStatus(statusLine, "上传中...", false);

      try {
        const response = await fetch("/api/tasks", {
          method: "POST",
          body: formData,
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "上传失败");
        }
        window.location.assign(payload.detail_url);
      } catch (error) {
        setStatus(statusLine, error.message || "上传失败", true);
        submitButton.disabled = false;
      }
    });
  }

  function setupTaskPage(shell) {
    const taskId = shell.dataset.taskId;
    const statusBadge = document.querySelector("#task-status");
    const errorLine = document.querySelector("#task-error");
    const logOutput = document.querySelector("#log-output");
    const copyLogButton = document.querySelector("#copy-log-button");
    let logOffset = 0;
    let statusTimer = null;
    let logTimer = null;
    let resultLoaded = false;

    copyLogButton.addEventListener("click", async () => {
      await navigator.clipboard.writeText(logOutput.textContent || "");
      copyLogButton.textContent = "已复制";
      window.setTimeout(() => {
        copyLogButton.textContent = "复制";
      }, 1200);
    });

    async function pollStatus() {
      try {
        const response = await fetch(`/api/tasks/${taskId}`);
        const task = await response.json();
        if (!response.ok) {
          throw new Error(task.detail || "任务不存在");
        }

        setTaskStatus(statusBadge, task.status);
        errorLine.textContent = task.error || "";

        if (task.status === "succeeded") {
          stopPollingStatus();
          if (!resultLoaded) {
            resultLoaded = true;
            await loadResult(taskId);
          }
        }

        if (task.status === "failed") {
          stopPollingStatus();
        }
      } catch (error) {
        errorLine.textContent = error.message || "状态读取失败";
        stopPollingStatus();
      }
    }

    async function pollLog() {
      try {
        const response = await fetch(`/api/tasks/${taskId}/log?offset=${logOffset}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "日志读取失败");
        }
        logOffset = payload.offset;
        if (payload.content) {
          logOutput.textContent += payload.content;
          logOutput.scrollTop = logOutput.scrollHeight;
        }
      } catch (error) {
        errorLine.textContent = error.message || "日志读取失败";
        stopPollingLog();
      }
    }

    function stopPollingStatus() {
      if (statusTimer) {
        window.clearInterval(statusTimer);
        statusTimer = null;
      }
    }

    function stopPollingLog() {
      if (logTimer) {
        window.clearInterval(logTimer);
        logTimer = null;
      }
    }

    pollStatus();
    pollLog();
    statusTimer = window.setInterval(pollStatus, 2000);
    logTimer = window.setInterval(pollLog, 2000);
  }

  async function loadResult(taskId) {
    const response = await fetch(`/api/tasks/${taskId}/result`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "结果读取失败");
    }

    const resultPanel = document.querySelector("#result-panel");
    const subtitleDownload = document.querySelector("#subtitle-download");
    const subtitleTitle = document.querySelector("#subtitle-title");
    const subtitleBody = document.querySelector("#subtitle-body");
    const clipList = document.querySelector("#clip-list");
    const player = document.querySelector("#clip-player");

    subtitleDownload.href = payload.subtitle.path;
    subtitleTitle.textContent = `字幕 ${payload.subtitle.filename}`;
    subtitleBody.innerHTML = "";
    for (const row of payload.subtitle.rows) {
      const tr = document.createElement("tr");
      appendCell(tr, row.index);
      appendCell(tr, row.start);
      appendCell(tr, row.end);
      appendCell(tr, row.text, "subtitle-text");
      subtitleBody.appendChild(tr);
    }

    clipList.innerHTML = "";
    for (const clip of payload.clips) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "clip-button";
      button.textContent = clip.filename;
      button.addEventListener("click", () => {
        player.src = clip.url;
        player.play();
      });
      clipList.appendChild(button);
    }

    if (payload.clips.length > 0) {
      player.src = payload.clips[0].url;
    }

    resultPanel.classList.remove("hidden");
  }

  function appendCell(row, value, className) {
    const td = document.createElement("td");
    if (className) {
      td.className = className;
    }
    td.textContent = value;
    row.appendChild(td);
  }

  function setStatus(element, text, isError) {
    element.textContent = text;
    element.classList.toggle("is-error", Boolean(isError));
  }

  function setTaskStatus(element, status) {
    element.textContent = status;
    element.dataset.status = status;
  }
})();
