document.addEventListener("DOMContentLoaded", () => {
    const vqcFilterLog = document.getElementById("vqc-filter-log");
    const vqcNoiseLog = document.getElementById("vqc-noise-log");

    const scrollToBottom = (element) => {
        // Use smooth scrolling if preferred, but instant is better for fast logs
        element.scrollTop = element.scrollHeight;
    };

    const appendLog = (container, message) => {
        if (!message) return; // Ignore empty frames
        
        const line = document.createElement("div");
        line.className = "log-line";
        
        // Colorize certain keywords for cinematic effect
        if (message.includes("[SYSTEM]")) {
            line.classList.add("system-msg");
        } else if (message.includes("⚠️") || message.includes("High Noise")) {
            line.style.color = "#ef4444"; // Red for warnings
        } else if (message.includes("✅") || message.includes("Clean Signal")) {
            line.style.color = "#10b981"; // Green for good state
        } else if (message.includes("STABLE")) {
            line.style.color = "#3b82f6"; // Blue for stable
        }
        
        line.textContent = message;
        container.appendChild(line);
        
        // Retain max 200 lines to prevent DOM bloated slowdowns
        if (container.children.length > 200) {
            container.removeChild(container.firstChild);
        }
        
        scrollToBottom(container);
    };

    // Initialize Server-Sent Events for VQC Filter
    const sseVqcFilter = new EventSource("/stream/vqc_filter");
    sseVqcFilter.onmessage = (event) => {
        appendLog(vqcFilterLog, event.data);
    };
    sseVqcFilter.onerror = () => {
        console.error("VQC Filter Stream Disconnected.");
    };

    // Initialize Server-Sent Events for VQC Noise Filter
    const sseVqcNoise = new EventSource("/stream/vqc_noise_filter");
    sseVqcNoise.onmessage = (event) => {
        appendLog(vqcNoiseLog, event.data);
    };
    sseVqcNoise.onerror = () => {
        console.error("VQC Noise Filter Stream Disconnected.");
    };
});
