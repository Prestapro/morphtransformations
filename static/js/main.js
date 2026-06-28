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
    const infResultBox = document.getElementById("inf-result-box");
    
    const builderNumber = document.getElementById("builder-number");
    const builderGender = document.getElementById("builder-gender");
    const builderCase = document.getElementById("builder-case");
    const builderTense = document.getElementById("builder-tense");
    const builderPerson = document.getElementById("builder-person");

    const infPosContainer = document.getElementById("inf-pos-container");
    const posPillsContainer = infPosContainer.querySelector(".pos-pills-container");
    let activePos = null;
    
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
                              tab.id === "tab-inflect" ? "sec-inflect" : 
                              tab.id === "tab-executor" ? "sec-executor" : "sec-rules";
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
                
                // Established status badge
                if (data.established) {
                    html += `
                        <div style="text-align: center; margin-bottom: 20px;">
                            <span class="rule-badge" style="background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.25); font-size: 0.8rem; padding: 4px 12px; border-radius: 20px; font-weight: 600;">
                                Устоявшееся слово (есть в словаре)
                            </span>
                        </div>
                    `;
                } else {
                    html += `
                        <div style="text-align: center; margin-bottom: 20px;">
                            <span class="rule-badge" style="background: rgba(168, 85, 247, 0.1); color: var(--accent); border: 1px solid rgba(168, 85, 247, 0.25); font-size: 0.8rem; padding: 4px 12px; border-radius: 20px; font-weight: 600;">
                                Разговорное / неологизм (нет в словаре)
                            </span>
                        </div>
                    `;
                }
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
    // Dynamic POS Selection & Form Constraints
    // -----------------------------------------------------------------------
    function updateBuilderState() {
        if (!activePos) {
            builderNumber.disabled = false;
            builderGender.disabled = false;
            builderCase.disabled = false;
            builderTense.disabled = false;
            builderPerson.disabled = false;
            return;
        }

        // Initialize all as disabled
        builderNumber.disabled = true;
        builderGender.disabled = true;
        builderCase.disabled = true;
        builderTense.disabled = true;
        builderPerson.disabled = true;

        if (activePos === "NOUN") {
            // Nouns decline by number, case, and allow cognate gender matching
            builderNumber.disabled = false;
            builderGender.disabled = false;
            builderCase.disabled = false;
        } else if (["ADJF", "ADJS", "PRTF", "PRTS"].includes(activePos)) {
            // Adjectives and full participles decline by number, gender, and case
            // Short adjectives/participles do not decline by case
            builderNumber.disabled = false;
            builderGender.disabled = false;
            if (activePos === "ADJF" || activePos === "PRTF") {
                builderCase.disabled = false;
            }
        } else if (activePos === "VERB") {
            // Finite verbs conjugate by tense, number, person (present/future) and gender (past)
            builderTense.disabled = false;
            builderNumber.disabled = false;
            
            if (builderTense.value === "past") {
                builderGender.disabled = false;
            } else if (builderTense.value === "pres" || builderTense.value === "futr") {
                builderPerson.disabled = false;
            } else {
                // Tense not selected: allow both gender and person until one is chosen
                builderGender.disabled = false;
                builderPerson.disabled = false;
            }
        } else if (activePos === "NUMR" || activePos === "NPRO") {
            // Numerals and pronouns decline by case, and some by gender/number
            builderCase.disabled = false;
            builderNumber.disabled = false;
            builderGender.disabled = false;
        } else {
            // Invariable parts of speech (INFN, GRND, COMP, ADVB, PRED, PREP, CONJ, PRCL, INTJ)
            // remain completely disabled.
        }

        // Clear values of disabled elements to avoid submitting hidden state
        if (builderNumber.disabled) builderNumber.value = "";
        if (builderGender.disabled) builderGender.value = "";
        if (builderCase.disabled) builderCase.value = "";
        if (builderTense.disabled) builderTense.value = "";
        if (builderPerson.disabled) builderPerson.value = "";
    }

    builderTense.addEventListener("change", () => {
        updateBuilderState();
    });

    let analyzeTimeout = null;
    infInput.addEventListener("input", () => {
        clearTimeout(analyzeTimeout);
        analyzeTimeout = setTimeout(async () => {
            const word = infInput.value.trim();
            if (!word) {
                infPosContainer.style.display = "none";
                posPillsContainer.innerHTML = "";
                activePos = null;
                updateBuilderState();
                return;
            }

            try {
                const data = await postData("/api/analyze", { word });
                if (data.interpretations && data.interpretations.length > 0) {
                    infPosContainer.style.display = "block";
                    let html = "";
                    data.interpretations.forEach((inter, idx) => {
                        html += `<button type="button" class="pos-pill" data-pos="${inter.pos}">${inter.lemma} (${inter.pos_ru})</button>`;
                    });
                    posPillsContainer.innerHTML = html;

                    const pills = posPillsContainer.querySelectorAll(".pos-pill");
                    pills.forEach(pill => {
                        pill.addEventListener("click", () => {
                            pills.forEach(p => p.classList.remove("active"));
                            pill.classList.add("active");
                            activePos = pill.getAttribute("data-pos");
                            updateBuilderState();
                        });
                    });

                    pills[0].click();
                } else {
                    infPosContainer.style.display = "none";
                    posPillsContainer.innerHTML = "";
                    activePos = null;
                    updateBuilderState();
                }
            } catch (err) {
                console.error("Error analyzing word POS:", err);
            }
        }, 300);
    });

    // -----------------------------------------------------------------------
    // Inflector Execution Logic
    // -----------------------------------------------------------------------
    runInflectBtn.addEventListener("click", async () => {
        const word = infInput.value.trim();
        
        const activeGrams = [];
        if (builderNumber.value) activeGrams.push(builderNumber.value);
        if (builderGender.value) activeGrams.push(builderGender.value);
        if (builderCase.value) activeGrams.push(builderCase.value);
        if (builderTense.value) activeGrams.push(builderTense.value);
        if (builderPerson.value) activeGrams.push(builderPerson.value);
        
        const grammemes = activeGrams.join(",");

        if (!word) {
            infResultBox.innerHTML = `<div class="empty-state">Введите слово для склонения</div>`;
            infResultBox.classList.add("empty");
            return;
        }

        if (!grammemes) {
            infResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Выберите хотя бы один грамматический признак в конструкторе</div>`;
            infResultBox.classList.add("empty");
            return;
        }

        infResultBox.innerHTML = `<div class="empty-state">Вычисление...</div>`;
        infResultBox.classList.remove("empty");

        try {
            const data = await postData("/api/inflect", { word, grammemes, pos: activePos });
            
            if (data.detail) {
                infResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">${data.detail}</div>`;
                infResultBox.classList.add("empty");
                return;
            }

            // Build HTML
            let html = "";

            if (data.interpretations && data.interpretations.length > 0) {
                if (data.interpretations.length > 1) {
                    html += `<div class="status-alert success" style="margin-bottom: 20px; font-weight: 500; text-align: center; background: rgba(99, 102, 241, 0.1); border-color: rgba(99, 102, 241, 0.25); color: var(--primary);">
                        Обнаружена омонимия: ${data.interpretations.length} варианта трактовки слова
                    </div>`;
                }

                data.interpretations.forEach(inter => {
                    const statusClass = inter.applicable ? "success" : "blocked";
                    const isApplicableText = inter.applicable ? "успешно" : "неприменимо";
                    
                    html += `
                        <div class="rule-card-inline" style="margin-bottom: 16px; border-left: 4px solid ${inter.applicable ? 'var(--success)' : 'var(--danger)'}; text-align: left; width: 100%;">
                            <h4 style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <span>Лемма: <strong style="color: #ffffff;">${inter.lemma}</strong> (${inter.pos})</span>
                                <span class="rule-badge" style="margin: 0; padding: 2px 8px; font-size: 0.75rem; background: ${inter.applicable ? 'var(--success-bg)' : 'var(--danger-bg)'}; color: ${inter.applicable ? 'var(--success)' : 'var(--danger)'}; border: 1px solid ${inter.applicable ? 'var(--success-border)' : 'var(--danger-border)'};">
                                    ${isApplicableText}
                                </span>
                            </h4>
                    `;

                    if (inter.applicable) {
                        const resWord = inter.result;
                        if (resWord.includes(" ")) {
                            const parts = resWord.split(" ");
                            const aux = parts[0];
                            const inf = parts.slice(1).join(" ");
                            html += `
                                <div class="split-word" style="font-size: 2rem; margin: 12px 0 0 0; text-align: left; padding-left: 8px; display: flex; align-items: baseline; gap: 8px;">
                                    <span class="suf-hl" style="font-size: 1.4rem; font-weight: 400; opacity: 0.85;">${aux}</span>
                                    <span class="stem-hl">${inf}</span>
                                </div>
                                <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 4px; padding-left: 8px;">
                                    Сложная аналитическая форма будущего времени (быть + инфинитив)
                                </div>
                            `;
                        } else {
                            let i = 0;
                            while (i < minLen(word, resWord) && word[i] === resWord[i]) {
                                i += 1;
                            }
                            const stem = resWord.slice(0, i);
                            const resSuf = resWord.slice(i);
                            
                            html += `
                                <div class="split-word" style="font-size: 2rem; margin: 12px 0 0 0; text-align: left; padding-left: 8px;">
                                    <span class="stem-hl">${stem}</span><span class="suf-hl">${resSuf || '-'}</span>
                                </div>
                            `;
                        }
                    } else {
                        html += `
                            <p style="margin-top: 8px; font-size: 0.9rem; color: var(--text-secondary); padding-left: 8px;">
                                ${inter.reason}
                            </p>
                        `;
                    }

                    html += `</div>`;
                });
            } else {
                const resWord = data.result;
                if (resWord.includes(" ")) {
                    const parts = resWord.split(" ");
                    const aux = parts[0];
                    const inf = parts.slice(1).join(" ");
                    html += `
                        <div class="split-word" style="display: flex; align-items: baseline; gap: 8px;">
                            <span class="suf-hl" style="font-size: 1.4rem; font-weight: 400; opacity: 0.85;">${aux}</span>
                            <span class="stem-hl">${inf}</span>
                        </div>
                    `;
                } else {
                    let i = 0;
                    while (i < minLen(word, resWord) && word[i] === resWord[i]) {
                        i += 1;
                    }
                    const stem = resWord.slice(0, i);
                    const resSuf = resWord.slice(i);

                    html += `<div class="split-word"><span class="stem-hl">${stem}</span><span class="suf-hl">${resSuf}</span></div>`;
                }
                if (data.warning) {
                    html += `<div class="status-alert blocked">${data.warning}</div>`;
                } else {
                    html += `<div class="status-alert success">Форма успешно извлечена из базы парадигм.</div>`;
                }
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

    // -----------------------------------------------------------------------
    // Execution UI Handlers
    // -----------------------------------------------------------------------
    let activeTarget = "browser";
    const targetBrowserBtn = document.getElementById("btn-target-browser");
    const targetTerminalBtn = document.getElementById("btn-target-terminal");

    targetBrowserBtn.addEventListener("click", () => {
        targetBrowserBtn.classList.add("active");
        targetTerminalBtn.classList.remove("active");
        activeTarget = "browser";
    });

    targetTerminalBtn.addEventListener("click", () => {
        targetTerminalBtn.classList.add("active");
        targetBrowserBtn.classList.remove("active");
        activeTarget = "terminal";
    });

    const runExecuteBtn = document.getElementById("btn-run-execute");
    const execInputCode = document.getElementById("exec-input-code");
    const execEnvTime = document.getElementById("exec-env-time");
    const execResultBox = document.getElementById("exec-result-box");

    // Pre-populate with current local computer time dynamically
    const updateLocalTimeFields = () => {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const timeStr = `${hrs}:${mins}`;
        
        execEnvTime.value = timeStr;
        execInputCode.value = `если сейчас ${timeStr} покажи зеленый квадрат`;
    };
    updateLocalTimeFields();

    runExecuteBtn.addEventListener("click", async () => {
        const code = execInputCode.value.trim();
        let timeVal = execEnvTime.value.trim();
        
        // If field is cleared, fallback to the current local browser time
        if (!timeVal) {
            const now = new Date();
            const hrs = String(now.getHours()).padStart(2, '0');
            const mins = String(now.getMinutes()).padStart(2, '0');
            timeVal = `${hrs}:${mins}`;
        }
        
        if (!code) {
            execResultBox.innerHTML = `<div class="empty-state">Введите код/инструкцию</div>`;
            execResultBox.classList.add("empty");
            return;
        }

        execResultBox.innerHTML = `<div class="empty-state">Выполнение...</div>`;
        execResultBox.classList.remove("empty");

        try {
            const data = await postData("/api/execute", {
                code: code,
                env: {
                    current_time: timeVal
                },
                runtime: {
                    target: activeTarget
                }
            });

            if (data.status === "unsupported") {
                execResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger); font-weight: 500;">${data.message}</div>`;
                return;
            }

            if (data.status === "condition_false") {
                execResultBox.innerHTML = `
                    <div style="width: 100%; text-align: center;">
                        <div class="status-alert blocked" style="margin-bottom: 20px; font-weight: 500;">
                            Условие не выполнено (время не совпадает)
                        </div>
                        <p style="color: var(--text-secondary); font-size: 0.9rem;">
                            Ожидалось: <b>${timeVal || 'текущее'}</b>. Попробуйте изменить имитируемое время в настройках.
                        </p>
                    </div>
                `;
                return;
            }

            if (data.status === "success") {
                let html = "";
                // Show status alert
                html += `
                    <div class="status-alert success" style="margin-bottom: 24px; font-weight: 500; width: 100%; text-align: center;">
                        Инструкция выполнена успешно: ${data.action || 'действие завершено'}
                    </div>
                `;

                if (activeTarget === "browser") {
                    // Browser output (SVG)
                    html += `
                        <div class="render-viewport" style="display: flex; align-items: center; justify-content: center; width: 100%; height: 200px;">
                            ${data.payload}
                        </div>
                    `;
                } else {
                    // Terminal output (ANSI)
                    const parsedAnsi = ansiToHtml(data.payload);
                    html += `
                        <div class="terminal-mockup" style="width: 100%; font-family: 'Inter', monospace; background: #000; color: #fff; padding: 20px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); line-height: 1.1; overflow-x: auto; text-align: left;">
                            <div style="color: var(--text-secondary); margin-bottom: 12px; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px;">[Terminal Console Output]</div>
                            <pre style="margin: 0; font-family: monospace; white-space: pre;">${parsedAnsi}</pre>
                        </div>
                    `;
                }

                execResultBox.innerHTML = html;
            }

        } catch (err) {
            console.error(err);
            execResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
            execResultBox.classList.add("empty");
        }
    });

    function ansiToHtml(ansiStr) {
        let html = ansiStr;
        // Escape HTML tags to prevent injections
        html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        // TrueColor background: \x1b[48;2;R;G;Bm
        const trueColorBgRegex = /\x1b\[48;2;(\d+);(\d+);(\d+)m/g;
        html = html.replace(trueColorBgRegex, (match, r, g, b) => {
            return `<span style="background-color: rgb(${r},${g},${b}); display: inline-block;">`;
        });
        // 16-color background (fallback): \x1b[4\d+m
        const fallbackBgRegex = /\x1b\[4\d+m/g;
        html = html.replace(fallbackBgRegex, '<span style="background-color: #2ecc71; display: inline-block;">');
        // Reset: \x1b[0m
        const resetRegex = /\x1b\[0m/g;
        html = html.replace(resetRegex, '</span>');
        
        return html;
    }

    execInputCode.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            runExecuteBtn.click();
        }
    });

    // Initial load
    loadRulesCatalog();
});
