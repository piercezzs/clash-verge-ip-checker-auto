function app() {
  return {
    context: null,
    profiles: [],
    selectedUid: "",
    error: "",
    notice: "",
    isRunning: false,
    runningAction: "",
    showProgress: false,
    progress: 0,
    total: 0,
    currentNode: "",
    rawNodes: [],
    nodes: [],
    selected: [],
    selectionTouched: false,
    loadedCheckedDate: "",
    loadedCheckedAt: "",
    loadedCached: 0,
    loadedTotal: 0,
    loadedCacheTtlDays: 14,
    dedupeRemoved: 0,
    exportedFiles: [],
    mobileModeAvailable: false,
    workspaceView: "nodes",
    expandedExportFile: "",
    isExporting: false,
    isImporting: false,
    isCopyingYaml: false,
    isCopyingMobileUrl: false,
    copyingExportedFile: "",
    editingId: null,
    editValue: "",
    exportedYaml: "",
    exportFilename: "",
    exportUrl: "",
    mobileSubscriptionUrl: "",
    importUrl: "",
    importStatus: "",
    importMessage: "",
    eventSource: null,
    controllerSecretKnown: false,
    config: {
      app_home: "",
      fast_mode: true,
      source: "ippure",
      fallback: false,
      selector_name: "auto",
      clash_api_url: "",
      clash_api_secret: "",
      refresh_remote: false,
      headless: true,
      temp_load_profile: false,
      force_refresh_ip_cache: false,
      output_suffix: "_checked",
      skip_keywords_str:
        "剩余,重置,到期,有效期,官网,网址,更新,公告,建议,新用户,无法订阅,邀请码,收藏,尝试,com",
    },

    async init() {
      window.addEventListener("beforeunload", () => this.closeSSE());
      this.$watch("selectedUid", async () => {
        if (!this.isRunning) await this.loadProfileResults();
      });
      this.$watch("config.fast_mode", async () => {
        if (!this.isRunning) await this.loadProfileResults();
      });
      await this.discover();
      await this.loadProfileResults();
      await this.loadExportedFiles();
    },

    async discover() {
      this.error = "";
      this.notice = "";
      const query = this.config.app_home.trim()
        ? `?app_home=${encodeURIComponent(this.config.app_home.trim())}`
        : "";
      try {
        const res = await fetch(`/api/verge/discover${query}`);
        const data = await res.json();
        this.context = data;
        this.profiles = data.profiles || [];
        this.config.app_home = data.app_home || this.config.app_home;
        this.config.clash_api_url = data.controller_url;
        this.controllerSecretKnown = Boolean(data.has_controller_secret);
        const current = this.supportedProfiles.find((p) => p.is_current);
        const first = this.supportedProfiles[0];
        const nextUid = current?.uid || first?.uid || "";
        this.selectedUid = nextUid;
        if (data.issues?.length) this.notice = data.issues.join("；");
      } catch (err) {
        this.error = `发现失败: ${err.message}`;
      }
    },

    get supportedProfiles() {
      return this.profiles.filter((p) => p.supported);
    },

    get unsupportedProfiles() {
      return this.profiles.filter((p) => !p.supported);
    },

    get selectedProfile() {
      return this.profiles.find((p) => p.uid === this.selectedUid) || null;
    },

    get isLanMode() {
      const hostname = window.location.hostname.toLowerCase();
      return !(
        hostname === "localhost" ||
        hostname === "0.0.0.0" ||
        hostname === "::1" ||
        hostname === "[::1]" ||
        hostname.startsWith("127.")
      ) || this.mobileModeAvailable;
    },

    get showAuxMetric() {
      const field = this.config.fast_mode ? "shared" : "bot";
      return this.nodes.some((node) => {
        const value = String(node[field] || "").trim();
        return value && value !== "N/A" && value !== "❓";
      });
    },

    get resultMetaText() {
      if (!this.loadedCheckedDate) return "";
      const checkedAt = this.loadedCheckedAt
        ? this.loadedCheckedAt.replace("T", " ")
        : this.loadedCheckedDate;
      return `${checkedAt} · 缓存 ${this.loadedCached}/${this.loadedTotal}`;
    },

    get dedupeText() {
      if (!this.dedupeRemoved) return "";
      return `去重 ${this.rawNodes.length}→${this.nodes.length}`;
    },

    async loadExportedFiles() {
      try {
        const res = await fetch("/api/exports");
        if (!res.ok) return;
        const data = await res.json();
        this.exportedFiles = data.files || [];
        this.mobileModeAvailable = this.exportedFiles.some(
          (file) => Boolean(file.mobile_subscription_url),
        );
      } catch (_err) {
        this.exportedFiles = [];
        this.mobileModeAvailable = false;
      }
    },

    toggleExportDetails(file) {
      if (!file?.mobile_subscription_url) return;
      this.expandedExportFile =
        this.expandedExportFile === file.filename ? "" : file.filename;
    },

    formatFileSize(bytes) {
      const size = Number(bytes) || 0;
      if (size < 1024) return `${size} B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${(size / 1024 / 1024).toFixed(1)} MB`;
    },

    async loadProfileResults() {
      if (!this.selectedUid || this.isRunning) return;
      this.error = "";
      this.notice = "";
      this.setNodes([]);
      this.selected = [];
      this.selectionTouched = false;
      this.loadedCheckedDate = "";
      this.loadedCheckedAt = "";
      this.loadedCached = 0;
      this.loadedTotal = 0;
      this.showProgress = false;
      this.progress = 0;
      this.total = 0;
      this.currentNode = "";
      try {
        const res = await fetch("/api/load-profile-results", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            app_home: this.config.app_home,
            profile_uid: this.selectedUid,
            config: this.config,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          this.error = err.detail || "加载缓存失败";
          return;
        }
        const data = await res.json();
        this.total = data.total || this.nodes.length;
        this.loadedCheckedDate = data.checked_date || "";
        this.loadedCheckedAt = data.checked_at || "";
        this.loadedCached = data.cached || 0;
        this.loadedTotal = data.total || 0;
        this.loadedCacheTtlDays = data.cache_ttl_days || 14;
        const cacheWarning = data.cache_warning || "";
        if (data.checked_date) {
          this.setNodes(data.nodes || []);
          this.applyRecommendedSelection();
        }
        if (cacheWarning) {
          this.notice = cacheWarning;
        }
      } catch (err) {
        this.error = `加载缓存失败: ${err.message}`;
      }
    },

    async startCheck(refreshRemote = false) {
      if (!this.selectedUid || this.isRunning) return;
      this.error = "";
      this.notice = "";
      this.progress = 0;
      this.setNodes([]);
      this.selected = [];
      this.selectionTouched = false;
      this.loadedCheckedDate = "";
      this.loadedCheckedAt = "";
      this.loadedCached = 0;
      this.loadedTotal = 0;
      this.exportedYaml = "";
      this.mobileSubscriptionUrl = "";
      this.importUrl = "";
      this.importStatus = "";
      this.importMessage = "";
      this.runningAction = refreshRemote ? "refresh" : "current";

      try {
        const runConfig = {
          ...this.config,
          source: "ippure",
          fallback: false,
          refresh_remote: Boolean(refreshRemote),
        };
        const res = await fetch("/api/start-profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            app_home: this.config.app_home,
            profile_uid: this.selectedUid,
            config: runConfig,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          this.error = err.detail || "启动失败";
          this.isRunning = false;
          this.runningAction = "";
          this.showProgress = false;
          return;
        }
        const data = await res.json();
        this.total = data.total;
        this.isRunning = true;
        this.showProgress = true;
        if (data.source_refreshed) {
          this.notice =
            "已拉取远程订阅最新内容，本次检测不会改动 Clash Verge 原订阅文件";
        }

        const nodesRes = await fetch("/api/nodes");
        const nodesData = await nodesRes.json();
        this.setNodes(nodesData.nodes || []);
        this.applyRecommendedSelection();
        this.connectSSE();
      } catch (err) {
        this.isRunning = false;
        this.runningAction = "";
        this.showProgress = false;
        this.error = `请求失败: ${err.message}`;
      }
    },

    connectSSE() {
      this.closeSSE();
      this.eventSource = new EventSource("/api/progress");
      this.eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "progress") {
          this.progress = data.progress;
          this.currentNode = data.node?.original_name || "";
          this.upsertNode(data.node);
        } else if (data.type === "message") {
          this.notice = data.message;
        } else if (data.type === "complete") {
          const completed = data.total || this.total || this.progress;
          const cacheHits = data.cache_hits || 0;
          const freshQueries = data.fresh_queries || 0;
          const partialResults = data.partial_results || 0;
          const failures = data.failures || 0;
          const cacheWarning = data.cache_warning || "";
          this.isRunning = false;
          this.runningAction = "";
          this.showProgress = false;
          this.currentNode = "";
          this.notice = `完成 ${completed} 个 · 缓存 ${cacheHits} · 新查 ${freshQueries} · 无评分 ${partialResults} · 失败 ${failures} · 已选 ${this.selected.length}`;
          if (cacheWarning) this.notice = `${this.notice}；${cacheWarning}`;
          this.closeSSE();
        } else if (data.type === "stopped") {
          this.isRunning = false;
          this.runningAction = "";
          this.showProgress = false;
          this.currentNode = "已停止";
          this.closeSSE();
        } else if (data.type === "error") {
          this.isRunning = false;
          this.runningAction = "";
          this.showProgress = false;
          this.error = data.error || "检测失败";
          this.closeSSE();
        }
      };
      this.eventSource.onerror = () => {
        if (!this.isRunning) this.closeSSE();
      };
    },

    closeSSE() {
      if (this.eventSource) {
        this.eventSource.close();
        this.eventSource = null;
      }
    },

    upsertNode(node) {
      if (!node) return;
      const idx = this.rawNodes.findIndex((item) => item.id === node.id);
      if (idx >= 0) {
        this.rawNodes.splice(idx, 1, node);
      } else {
        this.rawNodes.push(node);
      }
      this.refreshDisplayedNodes();
      if (
        !this.selectionTouched &&
        this.nodes.some((item) => item.id === node.id) &&
        this.isRecommendedNode(node) &&
        !this.selected.includes(node.id)
      ) {
        this.selected.push(node.id);
      }
    },

    setNodes(nodes) {
      this.rawNodes = Array.isArray(nodes) ? nodes : [];
      this.refreshDisplayedNodes();
    },

    refreshDisplayedNodes() {
      const seenIps = new Set();
      const visibleNodes = [];
      for (const node of this.rawNodes) {
        const ip = String(node.ip || "").trim();
        if (this.isConcreteIp(ip)) {
          if (seenIps.has(ip)) continue;
          seenIps.add(ip);
        }
        visibleNodes.push(node);
      }
      this.nodes = visibleNodes;
      this.dedupeRemoved = Math.max(
        0,
        this.rawNodes.length - this.nodes.length,
      );
      const visibleIds = new Set(this.nodes.map((node) => node.id));
      this.selected = this.selected.filter((id) => visibleIds.has(id));
    },

    isConcreteIp(ip) {
      if (!ip || ip === "..." || ip === "❓" || ip.toUpperCase() === "N/A") {
        return false;
      }
      return true;
    },

    nodeTypeText(node) {
      const values = [node?.type, node?.native]
        .map((value) => String(value || "").trim())
        .filter((value) => value && value !== "N/A" && value !== "❓");
      return values.length ? values.join(" · ") : "—";
    },

    statusText(node) {
      const value = String(node?.status || node?.source || "").trim();
      if (!value || value === "..." || value === "❓") return "待检测";
      if (value.includes("缓存")) return "缓存";
      return value.replace(/^♻️\s*/, "");
    },

    statusClass(node) {
      return this.statusText(node) === "待检测"
        ? "node-status pending"
        : "node-status";
    },

    async stopCheck() {
      try {
        await fetch("/api/stop", { method: "POST" });
        this.isRunning = false;
        this.runningAction = "";
      } catch (err) {
        this.error = `停止失败: ${err.message}`;
      }
    },

    selectAll() {
      this.selectionTouched = true;
      this.selected = this.nodes.map((node) => node.id);
    },

    selectNone() {
      this.selectionTouched = true;
      this.selected = [];
    },

    toggleAll(event) {
      event.target.checked ? this.selectAll() : this.selectNone();
    },

    toggleNode(node, event) {
      this.selectionTouched = true;
      if (event.target.checked) {
        if (!this.selected.includes(node.id)) this.selected.push(node.id);
      } else {
        this.selected = this.selected.filter((id) => id !== node.id);
      }
    },

    applyRecommendedSelection() {
      this.selected = this.nodes
        .filter((node) => this.isRecommendedNode(node))
        .map((node) => node.id);
    },

    isRecommendedNode(node) {
      const risk = this.parsePercent(node.risk);
      return risk !== null && risk <= 30;
    },

    parsePercent(value) {
      if (
        value === undefined ||
        value === null ||
        value === "" ||
        value === "N/A" ||
        value === "❓"
      ) {
        return null;
      }
      const match = String(value).trim().match(/^(\d+(?:\.\d+)?)%$/);
      return match ? Number(match[1]) : null;
    },

    startEdit(node, event = null) {
      this.editingId = node.id;
      this.editValue = node.name;
      this.$nextTick(() => {
        const input = event?.target?.closest("tr")?.querySelector(".inline-edit");
        if (input) input.focus();
      });
    },

    async saveEdit(node) {
      if (this.editValue.trim() && this.editValue !== node.name) {
        await fetch(`/api/nodes/${node.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: this.editValue }),
        });
        node.name = this.editValue;
      }
      this.editingId = null;
    },

    cancelEdit() {
      this.editingId = null;
    },

    async deleteNode(node) {
      if (!confirm(`删除节点 "${node.original_name}"?`)) return;
      await fetch(`/api/nodes/${node.id}`, { method: "DELETE" });
      this.nodes = this.nodes.filter((item) => item.id !== node.id);
      this.selected = this.selected.filter((id) => id !== node.id);
    },

    async exportYaml() {
      if (this.isRunning) {
        this.notice = "检测任务执行中，完成或停止后再导出。";
        return;
      }
      if (!this.selected.length) {
        alert("请先选择节点");
        return;
      }
      if (this.isExporting) return;
      this.isExporting = true;
      this.importUrl = "";
      this.importStatus = "";
      this.importMessage = "";
      try {
        const res = await fetch("/api/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            node_ids: this.selected,
            output_suffix: this.config.output_suffix,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          alert(err.detail || "导出失败");
          return;
        }
        const data = await res.json();
        this.exportedYaml = data.yaml;
        this.exportFilename = data.filename;
        this.exportUrl = data.url;
        this.mobileSubscriptionUrl = data.mobile_subscription_url || "";
        this.importUrl = data.import_url || "";
        this.importStatus = data.import_status || (this.importUrl ? "new" : "unknown");
        const existingCount = Number(data.existing_profile_count) || 0;
        const existingNames = data.existing_profile_names || [];
        const existingName = existingNames[0] || `${this.selectedProfile?.name || "当前订阅"}${this.config.output_suffix}`;
        if (this.importStatus === "existing") {
          this.importMessage = existingCount > 1
            ? `已覆盖文件；Clash Verge 有 ${existingCount} 个对应订阅，请保留一个并刷新。`
            : `已覆盖文件；请在 Clash Verge 刷新“${existingName}”。`;
        } else if (this.importStatus === "unknown") {
          this.importMessage = data.import_lookup_warning || "已覆盖文件；无法确认是否已导入，本次不提供一键导入。";
        } else {
          this.importMessage = "未检测到对应订阅，首次导入即可。";
        }
        await this.loadExportedFiles();
        this.$nextTick(() => {
          this.$refs.exportModal.showModal();
          this.$refs.modalClose?.focus();
        });
      } catch (err) {
        alert(`导出失败: ${err.message}`);
      } finally {
        this.isExporting = false;
      }
    },

    downloadYaml() {
      const blob = new Blob([this.exportedYaml], {
        type: "application/x-yaml",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = this.exportFilename;
      link.click();
      URL.revokeObjectURL(url);
    },

    closeExportModal() {
      this.$refs.exportModal.close();
      this.$nextTick(() => this.$refs.exportButton?.focus());
    },

    async copyText(value) {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        return;
      }
      const input = document.createElement("textarea");
      input.value = value;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
    },

    async copyYaml() {
      if (this.isCopyingYaml) return;
      this.isCopyingYaml = true;
      try {
        await this.copyText(this.exportedYaml);
        alert("已复制");
      } finally {
        this.isCopyingYaml = false;
      }
    },

    async copyMobileSubscriptionUrl() {
      if (!this.mobileSubscriptionUrl) {
        alert("未生成手机订阅 URL");
        return;
      }
      if (this.isCopyingMobileUrl) return;
      this.isCopyingMobileUrl = true;
      try {
        await this.copyText(this.mobileSubscriptionUrl);
        alert("已复制手机订阅 URL");
      } finally {
        this.isCopyingMobileUrl = false;
      }
    },

    async copyExportedFileUrl(file) {
      if (!file?.mobile_subscription_url) {
        alert("未生成手机订阅 URL");
        return;
      }
      if (this.copyingExportedFile) return;
      this.copyingExportedFile = file.filename;
      try {
        await this.copyText(file.mobile_subscription_url);
        alert("已复制手机订阅 URL");
      } finally {
        this.copyingExportedFile = "";
      }
    },

    importToClash() {
      if (this.importStatus !== "new" || !this.importUrl) {
        alert("未生成导入链接");
        return;
      }
      const importUrl = this.importUrl;
      this.isImporting = true;
      this.importStatus = "launched";
      this.importUrl = "";
      this.importMessage = "已打开 Clash Verge，请确认导入。";
      window.location.href = importUrl;
      setTimeout(() => {
        this.isImporting = false;
      }, 1500);
    },

    qrImageUrl(value) {
      return value ? `/api/qr?text=${encodeURIComponent(value)}` : "";
    },

    getRiskClass(risk) {
      if (!risk || risk === "❓" || risk === "N/A") return "";
      const num = parseInt(risk);
      if (Number.isNaN(num)) return "";
      if (num <= 10) return "risk-white";
      if (num <= 30) return "risk-green";
      if (num <= 50) return "risk-yellow";
      if (num <= 70) return "risk-orange";
      if (num <= 90) return "risk-red";
      return "risk-black";
    },

    getSharedClass(shared) {
      if (!shared || shared === "N/A" || shared === "❓") return "";
      const nums = String(shared).match(/\d+/g);
      if (!nums?.length) return "";
      let upper = parseInt(nums[nums.length - 1]);
      if (String(shared).includes("+")) upper += 1;
      if (upper <= 10) return "shared-green";
      if (upper <= 100) return "shared-yellow";
      if (upper <= 1000) return "shared-orange";
      if (upper <= 10000) return "shared-red";
      return "shared-black";
    },
  };
}
