// main.js - Modern JS Client for Morphological Transformations

document.addEventListener("DOMContentLoaded", () => {
    // State Variables
    let activeStyle = "colloquial";

    // Selectors
    const tabs = document.querySelectorAll(".tab-btn");
    const contents = document.querySelectorAll(".tab-content");
    
    const colloquialBtn = document.getElementById("btn-style-colloquial");
    const officialBtn = document.getElementById("btn-style-official");
    
    const generateBtn = document.getElementById("btn-generate-fem");
    const femInput = document.getElementById("fem-input-word");
    const femResultBox = document.getElementById("fem-result-box");
    
    const runInflectBtn = document.getElementById("btn-run-inflect");
    const infInput = document.getElementById("inf-input-word");
    const infGramSelect = document.getElementById("inf-gram-select");
    const infResultBox = document.getElementById("inf-result-box");
    
    const rulesContainer = document.getElementById("rules-container");

    // -----------------------------------------------------------------------
    // Tab Navigation Logic
    // -----------------------------------------------------------------------
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => {
                t.classList.remove("active");
                t.setAttribute("aria-selected", "false");
            });
            contents.forEach(c => c.classList.remove("active"));
            
            tab.classList.add("active");
            tab.setAttribute("aria-selected", "true");
            
            const contentId = tab.id === "tab-feminitive" ? "sec-feminitive" : 
                              tab.id === "tab-inflect" ? "sec-inflect" : "sec-rules";
            document.getElementById(contentId).classList.add("active");
        });
    });

    // -----------------------------------------------------------------------
    // Style Register Toggle Logic
    // -----------------------------------------------------------------------
    colloquialBtn.addEventListener("click", () => {
        colloquialBtn.classList.add("active");
        officialBtn.classList.remove("active");
        activeStyle = "colloquial";
    });

    officialBtn.addEventListener("click", () => {
        officialBtn.classList.add("active");
        colloquialBtn.classList.remove("active");
        activeStyle = "official";
    });

    // -----------------------------------------------------------------------
    // API Calling Functions
    // -----------------------------------------------------------------------
    async function postData(url = "", data = {}) {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    }

    async function getData(url = "") {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    }

    // -----------------------------------------------------------------------
    // Feminitive Generation Logic
    // -----------------------------------------------------------------------
    generateBtn.addEventListener("click", async () => {
        const word = femInput.value.trim();
        if (!word) {
            femResultBox.innerHTML = `<div class="empty-state">Введите слово в текстовое поле</div>`;
            femResultBox.classList.add("empty");
            return;
        }

        femResultBox.innerHTML = `<div class="empty-state">Анализ...</div>`;
        femResultBox.classList.remove("empty");

        try {
            const data = await postData("/api/feminitive", { word, style: activeStyle });
            
            if (data.error) {
                femResultBox.innerHTML = `<div class="empty-state">${data.error}</div>`;
                femResultBox.classList.add("empty");
                return;
            }

            // Build HTML
            let html = "";
            
            // Visual LCP Split
            if (data.blocked) {
                html += `<div class="split-word"><span class="stem-hl">${word}</span></div>`;
            } else {
                html += `<div class="split-word"><span class="stem-hl">${data.stem}</span><span class="suf-hl">${data.fem_suffix}</span></div>`;
            }

            // Alert Box
            const alertClass = data.blocked ? "blocked" : "success";
            html += `<div class="status-alert ${alertClass}">${data.message}</div>`;

            // Inline Rule Card
            html += `
                <div class="rule-card-inline">
                    <h4>Сработавшее правило:</h4>
                    <p>${data.rule}</p>
                </div>
            `;

            femResultBox.innerHTML = html;

        } catch (err) {
            console.error(err);
            femResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
            femResultBox.classList.add("empty");
        }
    });

    // Enter Key Trigger
    femInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            generateBtn.click();
        }
    });

    // -----------------------------------------------------------------------
    // Inflector Execution Logic
    // -----------------------------------------------------------------------
    runInflectBtn.addEventListener("click", async () => {
        const word = infInput.value.trim();
        const grammemes = infGramSelect.value;
        if (!word) {
            infResultBox.innerHTML = `<div class="empty-state">Введите слово для склонения</div>`;
            infResultBox.classList.add("empty");
            return;
        }

        infResultBox.innerHTML = `<div class="empty-state">Вычисление...</div>`;
        infResultBox.classList.remove("empty");

        try {
            const data = await postData("/api/inflect", { word, grammemes });
            
            if (data.detail) {
                infResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">${data.detail}</div>`;
                infResultBox.classList.add("empty");
                return;
            }

            // LCP Split comparison between source and result
            const resWord = data.result;
            let i = 0;
            while (i < minLen(word, resWord) && word[i] === resWord[i]) {
                i += 1;
            }
            const stem = resWord.slice(0, i);
            const resSuf = resWord.slice(i);

            let html = `<div class="split-word"><span class="stem-hl">${stem}</span><span class="suf-hl">${resSuf}</span></div>`;
            
            if (data.warning) {
                html += `<div class="status-alert blocked">${data.warning}</div>`;
            } else {
                html += `<div class="status-alert success">Форма успешно извлечена из базы парадигм.</div>`;
            }

            infResultBox.innerHTML = html;

        } catch (err) {
            console.error(err);
            infResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
            infResultBox.classList.add("empty");
        }
    });

    function minLen(s1, s2) {
        return Math.min(s1.length, s2.length);
    }

    infInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            runInflectBtn.click();
        }
    });

    // -----------------------------------------------------------------------
    // Rules Catalog Loading
    // -----------------------------------------------------------------------
    async function loadRulesCatalog() {
        try {
            const data = await getData("/api/rules");
            let html = "";
            data.rules.forEach(rule => {
                html += `
                    <div class="rule-card">
                        <h3>${rule.suffix}</h3>
                        <div class="rule-badge">${rule.rule}</div>
                        <p>${rule.desc}</p>
                        <p style="margin-top: 12px; font-weight: 500; font-size: 0.85rem; color: var(--text-primary);">
                            Пример: ${rule.example}
                        </p>
                    </div>
                `;
            });
            rulesContainer.innerHTML = html;
        } catch (err) {
            console.error(err);
            rulesContainer.innerHTML = `<div class="empty-state" style="color: var(--danger); width: 100%;">Не удалось загрузить карту правил.</div>`;
        }
    }

    // Initial load
    loadRulesCatalog();
});
