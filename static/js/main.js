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
            
            const tabMap = {
                'tab-feminitive': 'sec-feminitive',
                'tab-inflect': 'sec-inflect',
                'tab-decompose': 'sec-decompose',
                'tab-cognates': 'sec-cognates',
                'tab-paradigm': 'sec-paradigm',
                'tab-suffix-stats': 'sec-suffix-stats',
                'tab-catalog': 'sec-catalog',
                'tab-morph-search': 'sec-morph-search',
                'tab-executor': 'sec-executor',
                'tab-rules-catalog': 'sec-rules'
            };
            const contentId = tabMap[tab.id] || 'sec-feminitive';
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
            builderNumber.disabled = false;
            builderGender.disabled = false;
            builderCase.disabled = false;
        } else if (["ADJF", "ADJS", "PRTF", "PRTS"].includes(activePos)) {
            builderNumber.disabled = false;
            builderGender.disabled = false;
            if (activePos === "ADJF" || activePos === "PRTF") {
                builderCase.disabled = false;
            }
        } else if (activePos === "VERB") {
            builderTense.disabled = false;
            builderNumber.disabled = false;
            
            if (builderTense.value === "past") {
                builderGender.disabled = false;
            } else if (builderTense.value === "pres" || builderTense.value === "futr") {
                builderPerson.disabled = false;
            } else {
                builderGender.disabled = false;
                builderPerson.disabled = false;
            }
        } else if (activePos === "NUMR" || activePos === "NPRO") {
            builderCase.disabled = false;
            builderNumber.disabled = false;
            builderGender.disabled = false;
        }

        // Clear values of disabled elements
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

            let html = "";

            if (data.interpretations && data.interpretations.length > 0) {
                if (data.interpretations.length > 1) {
                    html += `<div class="status-alert success" style="margin-bottom: 20px; font-weight: 500; text-align: center; background: rgba(99, 102, 241, 0.1); border-color: rgba(99, 102, 241, 0.25); color: var(--primary);">
                        Обнаружена омонимия: ${data.interpretations.length} варианта трактовки слова
                    </div>`;
                }

                data.interpretations.forEach(inter => {
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
    // Morpheme Decomposition
    // -----------------------------------------------------------------------
    const MORPH_COLORS = {
        PREFIX: { bg: 'rgba(99, 102, 241, 0.2)', border: 'rgba(99, 102, 241, 0.5)', color: '#818cf8', label: 'приставка' },
        ROOT: { bg: 'rgba(239, 68, 68, 0.2)', border: 'rgba(239, 68, 68, 0.5)', color: '#f87171', label: 'корень' },
        SUFFIX: { bg: 'rgba(16, 185, 129, 0.2)', border: 'rgba(16, 185, 129, 0.5)', color: '#34d399', label: 'суффикс' },
        ENDING: { bg: 'rgba(251, 191, 36, 0.2)', border: 'rgba(251, 191, 36, 0.5)', color: '#fbbf24', label: 'окончание' },
        LINKING: { bg: 'rgba(156, 163, 175, 0.2)', border: 'rgba(156, 163, 175, 0.5)', color: '#9ca3af', label: 'соед. гласная' }
    };

    const decInput = document.getElementById("dec-input-word");
    const decResultBox = document.getElementById("dec-result-box");
    const btnDecompose = document.getElementById("btn-run-decompose");

    btnDecompose.addEventListener("click", async () => {
        const word = decInput.value.trim();
        if (!word) { decResultBox.innerHTML = `<div class="empty-state">Введите слово</div>`; return; }
        decResultBox.innerHTML = `<div class="empty-state">Анализ...</div>`;
        try {
            const data = await postData("/api/decompose", { word });
            let html = '<div style="display: flex; flex-wrap: wrap; gap: 4px; align-items: center; justify-content: center; margin-bottom: 24px;">';
            data.morphemes.forEach((m, idx) => {
                const c = MORPH_COLORS[m.type] || MORPH_COLORS.ROOT;
                html += `<div style="display: flex; flex-direction: column; align-items: center;">
                    <span style="background: ${c.bg}; border: 2px solid ${c.border}; color: ${c.color}; padding: 10px 16px; border-radius: 12px; font-size: 1.6rem; font-weight: 700; font-family: 'Outfit', sans-serif;">${m.value}</span>
                    <span style="font-size: 0.7rem; color: ${c.color}; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">${c.label}</span>
                </div>`;
                if (idx < data.morphemes.length - 1) {
                    html += `<span style="color: var(--text-secondary); font-size: 1.2rem; padding: 0 2px;">+</span>`;
                }
            });
            html += '</div>';
            html += `<div class="status-alert success" style="text-align: center;">Источник: ${data.source === 'tikhonov' ? 'Словарь Тихонова (102K слов)' : 'Символьный fallback'}</div>`;
            decResultBox.innerHTML = html;
            decResultBox.classList.remove("empty");
        } catch (err) {
            console.error(err);
            decResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
        }
    });
    decInput.addEventListener("keypress", (e) => { if (e.key === "Enter") btnDecompose.click(); });

    // -----------------------------------------------------------------------
    // Cognate Words
    // -----------------------------------------------------------------------
    const cogInput = document.getElementById("cog-input-word");
    const cogResultBox = document.getElementById("cog-result-box");
    const btnCognates = document.getElementById("btn-run-cognates");

    btnCognates.addEventListener("click", async () => {
        const word = cogInput.value.trim();
        if (!word) { cogResultBox.innerHTML = `<div class="empty-state">Введите слово</div>`; return; }
        cogResultBox.innerHTML = `<div class="empty-state">Поиск...</div>`;
        try {
            const data = await postData("/api/cognates", { word });
            if (data.error) {
                cogResultBox.innerHTML = `<div class="empty-state">${data.error}</div>`;
                return;
            }
            let html = `<div style="text-align: center; margin-bottom: 16px;">
                <span style="font-size: 1.2rem; color: var(--text-secondary);">Корень: </span>
                <span style="font-size: 1.6rem; font-weight: 700; color: #f87171; font-family: 'Outfit', sans-serif;">${data.root}</span>
                <span style="font-size: 0.85rem; color: var(--text-secondary); margin-left: 8px;">(${data.total} слов)</span>
            </div>`;
            html += '<div style="display: flex; flex-wrap: wrap; gap: 8px; justify-content: center;">';
            data.cognates.forEach(w => {
                const isInput = w.toLowerCase() === word.toLowerCase();
                html += `<span style="padding: 6px 14px; border-radius: 20px; font-size: 0.9rem; font-weight: 500;
                    background: ${isInput ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255,255,255,0.04)'};
                    border: 1px solid ${isInput ? 'rgba(99, 102, 241, 0.4)' : 'var(--border-color)'};
                    color: ${isInput ? '#818cf8' : 'var(--text-primary)'};">${w}</span>`;
            });
            html += '</div>';
            cogResultBox.innerHTML = html;
            cogResultBox.classList.remove("empty");
        } catch (err) {
            console.error(err);
            cogResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
        }
    });
    cogInput.addEventListener("keypress", (e) => { if (e.key === "Enter") btnCognates.click(); });

    // -----------------------------------------------------------------------
    // Full Paradigm Table
    // -----------------------------------------------------------------------
    const parInput = document.getElementById("par-input-word");
    const parResultBox = document.getElementById("par-result-box");
    const btnParadigm = document.getElementById("btn-run-paradigm");

    const POS_NAMES_JS = {
        NOUN: "Существительное", ADJF: "Прилагательное (полное)", ADJS: "Прил. (краткое)",
        VERB: "Глагол (личная форма)", INFN: "Инфинитив", PRTF: "Причастие (полное)",
        PRTS: "Причастие (краткое)", GRND: "Деепричастие", COMP: "Компаратив",
        ADVB: "Наречие", NUMR: "Числительное", NPRO: "Местоимение"
    };

    btnParadigm.addEventListener("click", async () => {
        const word = parInput.value.trim();
        if (!word) { parResultBox.innerHTML = `<div class="empty-state">Введите лемму</div>`; return; }
        parResultBox.innerHTML = `<div class="empty-state">Загрузка...</div>`;
        try {
            const data = await postData("/api/paradigm", { word });
            if (data.error) {
                parResultBox.innerHTML = `<div class="empty-state">${data.error}</div>`;
                return;
            }
            let html = `<div style="text-align: center; margin-bottom: 16px;">
                <span style="font-size: 1.2rem; font-weight: 700; color: var(--text-primary); font-family: 'Outfit';">${data.lemma}</span>
                <span style="font-size: 0.85rem; color: var(--text-secondary); margin-left: 8px;">${data.forms.length} форм</span>
            </div>`;
            
            // Group by POS
            const groups = {};
            data.forms.forEach(f => {
                if (!groups[f.pos]) groups[f.pos] = [];
                groups[f.pos].push(f);
            });

            for (const [pos, forms] of Object.entries(groups)) {
                const posName = POS_NAMES_JS[pos] || pos;
                html += `<div style="margin-bottom: 16px;">
                    <div style="font-size: 0.8rem; font-weight: 600; color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; padding-left: 4px;">${posName}</div>
                    <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">`;
                forms.forEach((f, i) => {
                    const bg = i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent';
                    html += `<tr style="background: ${bg};">
                        <td style="padding: 6px 12px; color: var(--text-secondary); font-family: monospace; font-size: 0.75rem; width: 55%;">${f.grammemes}</td>
                        <td style="padding: 6px 12px; color: var(--text-primary); font-weight: 500;">${f.form}</td>
                    </tr>`;
                });
                html += `</table></div>`;
            }
            parResultBox.innerHTML = html;
            parResultBox.classList.remove("empty");
        } catch (err) {
            console.error(err);
            parResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
        }
    });
    parInput.addEventListener("keypress", (e) => { if (e.key === "Enter") btnParadigm.click(); });

    // -----------------------------------------------------------------------
    // Suffix Statistics
    // -----------------------------------------------------------------------
    const sufInput = document.getElementById("suf-input");
    const sufResultBox = document.getElementById("suf-result-box");
    const btnSuffix = document.getElementById("btn-run-suffix");

    btnSuffix.addEventListener("click", async () => {
        const suffix = sufInput.value.trim();
        if (!suffix) { sufResultBox.innerHTML = `<div class="empty-state">Введите суффикс</div>`; return; }
        sufResultBox.innerHTML = `<div class="empty-state">Анализ...</div>`;
        try {
            const data = await postData("/api/suffix_stats", { suffix });
            if (!data.stats || data.stats.length === 0) {
                sufResultBox.innerHTML = `<div class="empty-state">Суффикс «${suffix}» не найден в базе</div>`;
                return;
            }
            let html = `<div style="text-align: center; margin-bottom: 16px;">
                <span style="font-size: 1.4rem; font-weight: 700; color: var(--text-primary); font-family: 'Outfit';">-${suffix}</span>
                <span style="font-size: 0.85rem; color: var(--text-secondary); margin-left: 8px;">${data.total_count.toLocaleString()} словоформ</span>
            </div>`;
            
            data.stats.forEach(s => {
                const pct = (s.probability * 100).toFixed(1);
                const posName = POS_NAMES_JS[s.pos] || s.pos;
                const barWidth = Math.max(4, s.probability * 100);
                html += `<div style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <span style="font-size: 0.85rem; font-weight: 500; color: var(--text-primary);">${posName} ${s.grammemes ? '<span style="color: var(--text-secondary); font-size: 0.75rem; font-family: monospace;">' + s.grammemes + '</span>' : ''}</span>
                        <span style="font-size: 0.85rem; font-weight: 600; color: var(--accent);">${pct}%</span>
                    </div>
                    <div style="height: 6px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden;">
                        <div style="height: 100%; width: ${barWidth}%; background: linear-gradient(90deg, var(--primary), var(--accent)); border-radius: 3px; transition: width 0.5s ease;"></div>
                    </div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 2px;">${s.count.toLocaleString()} из ${s.total.toLocaleString()}</div>
                </div>`;
            });
            sufResultBox.innerHTML = html;
            sufResultBox.classList.remove("empty");
        } catch (err) {
            console.error(err);
            sufResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
        }
    });
    sufInput.addEventListener("keypress", (e) => { if (e.key === "Enter") btnSuffix.click(); });

    // -----------------------------------------------------------------------
    // Morpheme Catalog
    // -----------------------------------------------------------------------
    let catalogData = null;
    let activeCatalogTab = 'suffixes';
    const catalogContent = document.getElementById("catalog-content");
    const catBtns = {
        suffixes: document.getElementById("btn-cat-suffixes"),
        prefixes: document.getElementById("btn-cat-prefixes"),
        endings: document.getElementById("btn-cat-endings")
    };

    function renderCatalog(section) {
        if (!catalogData || !catalogData[section]) {
            catalogContent.innerHTML = `<div class="empty-state">Данные не загружены</div>`;
            return;
        }
        const data = catalogData[section];
        let html = '';
        
        // data is nested: POS → TYPE → items
        for (const [posKey, posData] of Object.entries(data)) {
            if (posKey === '_meta') continue;
            html += `<div style="margin-bottom: 24px; grid-column: 1 / -1;">
                <h3 style="font-family: 'Outfit'; font-size: 1.1rem; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-color);">${posKey}</h3>`;
            
            if (typeof posData === 'object' && !Array.isArray(posData)) {
                for (const [typeName, typeData] of Object.entries(posData)) {
                    if (typeof typeData === 'string' || typeof typeData === 'number') {
                        // Simple key-value (like 'note:')
                        continue;
                    }
                    html += `<div class="rule-card" style="margin-bottom: 8px;">
                        <h3 style="font-size: 0.9rem;">${typeName}</h3>`;
                    if (Array.isArray(typeData)) {
                        html += `<div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;">`;
                        typeData.forEach(item => {
                            html += `<span style="padding: 4px 10px; border-radius: 8px; font-size: 0.85rem; background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.25); color: #818cf8; font-weight: 500;">${item}</span>`;
                        });
                        html += '</div>';
                    } else if (typeof typeData === 'object') {
                        html += '<div style="margin-top: 8px;">';
                        for (const [formKey, formVal] of Object.entries(typeData)) {
                            if (typeof formVal === 'string') {
                                html += `<div style="display: flex; justify-content: space-between; padding: 3px 0; font-size: 0.8rem;">
                                    <span style="color: var(--text-secondary); font-family: monospace;">${formKey}</span>
                                    <span style="color: var(--text-primary); font-weight: 500;">${formVal}</span>
                                </div>`;
                            }
                        }
                        html += '</div>';
                    }
                    html += `</div>`;
                }
            }
            html += '</div>';
        }
        catalogContent.innerHTML = html || '<div class="empty-state">Нет данных</div>';
    }

    async function loadCatalog() {
        try {
            catalogData = await getData("/api/morphemes_catalog");
            if (catalogData.error) {
                catalogContent.innerHTML = `<div class="empty-state">${catalogData.error}</div>`;
                return;
            }
            renderCatalog(activeCatalogTab);
        } catch (err) {
            console.error(err);
            catalogContent.innerHTML = `<div class="empty-state" style="color: var(--danger);">Не удалось загрузить каталог.</div>`;
        }
    }

    Object.entries(catBtns).forEach(([key, btn]) => {
        btn.addEventListener("click", () => {
            Object.values(catBtns).forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            activeCatalogTab = key;
            renderCatalog(key);
        });
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
    const execResultBox = document.getElementById("exec-result-box");

    const updateLocalTimeFields = () => {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const timeStr = `${hrs}:${mins}`;
        execInputCode.value = `если сейчас ${timeStr} покажи зеленый квадрат`;
    };
    updateLocalTimeFields();

    runExecuteBtn.addEventListener("click", async () => {
        const code = execInputCode.value.trim();
        
        if (!code) {
            execResultBox.innerHTML = `<div class="empty-state">Введите код/инструкцию</div>`;
            execResultBox.classList.add("empty");
            return;
        }

        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const timeVal = `${hrs}:${mins}`;
        const dateVal = now.toISOString().split('T')[0];
        const langVal = navigator.language || "ru-RU";
        const tzVal = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

        execResultBox.innerHTML = `<div class="empty-state">Выполнение...</div>`;
        execResultBox.classList.remove("empty");

        try {
            const data = await postData("/api/execute", {
                code: code,
                env: { current_time: timeVal, date: dateVal, language: langVal, timezone: tzVal },
                runtime: { target: activeTarget }
            });

            if (data.status === "unsupported") {
                execResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger); font-weight: 500;">${data.message}</div>`;
                return;
            }

            if (data.status === "condition_false") {
                execResultBox.innerHTML = `
                    <div style="width: 100%; text-align: center;">
                        <div class="status-alert blocked" style="margin-bottom: 20px; font-weight: 500;">
                            Условие не выполнено (время или дата не совпадают)
                        </div>
                        <p style="color: var(--text-secondary); font-size: 0.9rem;">
                            Системное время: <b>${timeVal}</b>, дата: <b>${dateVal}</b>.
                        </p>
                    </div>
                `;
                return;
            }

            if (data.status === "success") {
                let html = "";
                html += `
                    <div class="status-alert success" style="margin-bottom: 24px; font-weight: 500; width: 100%; text-align: center;">
                        Инструкция выполнена успешно: ${data.action || 'действие завершено'}
                    </div>
                `;

                if (activeTarget === "browser") {
                    if (data.type === "canvas_widget") {
                        const canvasId = "result-canvas-" + Date.now();
                        html += `
                            <div class="render-viewport" style="display: flex; align-items: center; justify-content: center; width: 100%;">
                                <canvas id="${canvasId}" width="${data.payload.width}" height="${data.payload.height}" style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.4); max-width: 100%; aspect-ratio: 1;"></canvas>
                            </div>
                        `;
                        execResultBox.innerHTML = html;
                        const canvas = document.getElementById(canvasId);
                        if (canvas) {
                            const ctx = canvas.getContext("2d");
                            ctx.clearRect(0, 0, canvas.width, canvas.height);
                            const commands = data.payload.commands || [];
                            commands.forEach(cmd => {
                                if (cmd.op === "fillStyle") ctx.fillStyle = cmd.value;
                                else if (cmd.op === "strokeStyle") ctx.strokeStyle = cmd.value;
                                else if (cmd.op === "lineWidth") ctx.lineWidth = cmd.value;
                                else if (cmd.op === "beginPath") ctx.beginPath();
                                else if (cmd.op === "rect") ctx.rect(cmd.x, cmd.y, cmd.w, cmd.h);
                                else if (cmd.op === "fillRect") ctx.fillRect(cmd.x, cmd.y, cmd.w, cmd.h);
                                else if (cmd.op === "arc") ctx.arc(cmd.x, cmd.y, cmd.r, cmd.start, cmd.end);
                                else if (cmd.op === "fill") ctx.fill();
                                else if (cmd.op === "stroke") ctx.stroke();
                                else if (cmd.op === "moveTo") ctx.moveTo(cmd.x, cmd.y);
                                else if (cmd.op === "lineTo") ctx.lineTo(cmd.x, cmd.y);
                                else if (cmd.op === "closePath") ctx.closePath();
                            });
                        }
                    } else {
                        html += `
                            <div class="render-viewport" style="display: flex; align-items: center; justify-content: center; width: 100%; height: 200px;">
                                ${data.payload}
                            </div>
                        `;
                        execResultBox.innerHTML = html;
                    }
                } else {
                    const parsedAnsi = ansiToHtml(data.payload);
                    html += `
                        <div class="terminal-mockup" style="width: 100%; font-family: 'Inter', monospace; background: #000; color: #fff; padding: 20px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); line-height: 1.1; overflow-x: auto; text-align: left;">
                            <div style="color: var(--text-secondary); margin-bottom: 12px; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px;">[Terminal Console Output]</div>
                            <pre style="margin: 0; font-family: monospace; white-space: pre;">${parsedAnsi}</pre>
                        </div>
                    `;
                    execResultBox.innerHTML = html;
                }
            }

        } catch (err) {
            console.error(err);
            execResultBox.innerHTML = `<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>`;
            execResultBox.classList.add("empty");
        }
    });

    function ansiToHtml(ansiStr) {
        let html = ansiStr;
        html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const trueColorBgRegex = /\x1b\[48;2;(\d+);(\d+);(\d+)m/g;
        html = html.replace(trueColorBgRegex, (match, r, g, b) => {
            return `<span style="background-color: rgb(${r},${g},${b}); display: inline-block;">`;
        });
        const fallbackBgRegex = /\x1b\[4\d+m/g;
        html = html.replace(fallbackBgRegex, '<span style="background-color: #2ecc71; display: inline-block;">');
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

    // -----------------------------------------------------------------------
    // Morpheme Search (reverse lookup)
    // -----------------------------------------------------------------------
    const msrchInput = document.getElementById('msrch-input');
    const msrchResultBox = document.getElementById('msrch-result-box');
    const msrchHeader = document.getElementById('msrch-header');
    const btnMsrch = document.getElementById('btn-run-msrch');
    const msrchFilterRow = document.getElementById('msrch-filter-row');
    const msrchWordFilter = document.getElementById('msrch-word-filter');
    let activeMsrchType = 'any';

    const TYPE_LABELS = {
        prefix: 'приставка',
        suffix: 'суффикс',
        ending: 'окончание',
        root: 'корень',
        compound_root: '2-й корень (сложн.)'
    };
    const TYPE_COLORS = {
        prefix: { bg: 'rgba(99, 102, 241, 0.15)', border: 'rgba(99, 102, 241, 0.35)', color: '#818cf8' },
        suffix: { bg: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 0.35)', color: '#34d399' },
        ending: { bg: 'rgba(251, 191, 36, 0.15)', border: 'rgba(251, 191, 36, 0.35)', color: '#fbbf24' },
        root: { bg: 'rgba(239, 68, 68, 0.15)', border: 'rgba(239, 68, 68, 0.35)', color: '#f87171' },
        compound_root: { bg: 'rgba(251, 146, 60, 0.15)', border: 'rgba(251, 146, 60, 0.35)', color: '#fb923c' }
    };

    const msrchBtns = {
        any: document.getElementById('btn-msrch-any'),
        prefix: document.getElementById('btn-msrch-prefix'),
        suffix: document.getElementById('btn-msrch-suffix'),
        ending: document.getElementById('btn-msrch-ending'),
        root: document.getElementById('btn-msrch-root')
    };

    // Source toggle (independent from type)
    const btnSrcTikhonov = document.getElementById('btn-src-tikhonov');
    const btnSrcOpenCorpora = document.getElementById('btn-src-opencorpora');
    let useOpenCorpora = false;

    const posFilterGroup = document.getElementById('pos-filter-group');
    let activeEndPos = 'any';

    btnSrcTikhonov.addEventListener('click', () => {
        btnSrcTikhonov.classList.add('active');
        btnSrcOpenCorpora.classList.remove('active');
        useOpenCorpora = false;
        posFilterGroup.style.display = 'none';
    });
    btnSrcOpenCorpora.addEventListener('click', () => {
        btnSrcOpenCorpora.classList.add('active');
        btnSrcTikhonov.classList.remove('active');
        useOpenCorpora = true;
        posFilterGroup.style.display = 'block';
    });

    // POS filter buttons
    const endPosBtns = document.querySelectorAll('#pos-filter-group [data-pos]');
    endPosBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            endPosBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeEndPos = btn.dataset.pos;
        });
    });

    const POS_COLORS = {
        NOUN: { border: '#6366f1', color: '#818cf8' },
        ADJF: { border: '#10b981', color: '#34d399' },
        VERB: { border: '#f43f5e', color: '#fb7185' },
        INFN: { border: '#f97316', color: '#fb923c' },
        PRTF: { border: '#a855f7', color: '#c084fc' },
        GRND: { border: '#14b8a6', color: '#2dd4bf' },
        ADVB: { border: '#eab308', color: '#facc15' },
        ADJS: { border: '#22d3ee', color: '#67e8f9' },
        PRTS: { border: '#ec4899', color: '#f472b6' },
        COMP: { border: '#84cc16', color: '#a3e635' },
        NUMR: { border: '#8b5cf6', color: '#a78bfa' },
        NPRO: { border: '#64748b', color: '#94a3b8' },
    };

    // Type toggle (prefix/suffix/ending/root)
    Object.entries(msrchBtns).forEach(([key, btn]) => {
        btn.addEventListener('click', () => {
            Object.values(msrchBtns).forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeMsrchType = key;
        });
    });

    const chkNoLimit = document.getElementById('chk-no-limit');

    async function _runMsrchSearch(morpheme, wordFilter) {
        msrchResultBox.innerHTML = '<div class="empty-state">Поиск...</div>';

        const isOpenCorpora = useOpenCorpora;
        const noLimit = chkNoLimit && chkNoLimit.checked;

        try {
            let data;
            if (isOpenCorpora) {
                const stMap = { any: 'any', prefix: 'prefix', suffix: 'suffix', ending: 'ending', root: 'any' };
                const searchType = stMap[activeMsrchType] || 'ending';
                const params = {
                    ending: morpheme,
                    pos: activeEndPos,
                    search_type: searchType,
                };
                if (wordFilter) params.word_filter = wordFilter;
                if (noLimit) params.limit = 0;
                data = await postData('/api/ending_search', params);
            } else {
                data = await postData('/api/morpheme_search', { morpheme, morpheme_type: activeMsrchType });
            }

            if (data.total === 0) {
                msrchResultBox.innerHTML = `<div class="empty-state">«${morpheme}» не найдено</div>`;
                msrchHeader.textContent = 'Ничего не найдено';
                return;
            }

            const sourceLabel = isOpenCorpora ? 'OpenCorpora' : 'Тихонов';
            let modeLabel;
            if (isOpenCorpora) {
                const modeMap = { prefix: 'Начинаются на', suffix: 'Оканчиваются на', ending: 'Оканчиваются на', any: 'Содержат' };
                const stMap2 = { any: 'any', prefix: 'prefix', suffix: 'suffix', ending: 'ending', root: 'any' };
                modeLabel = modeMap[stMap2[activeMsrchType] || 'ending'] || 'Содержат';
            } else {
                modeLabel = 'Слова с';
            }

            // Coverage stats
            const cov = data.coverage || {};
            const covPct = cov.pct || 0;
            const covDecomp = cov.decomposed || 0;
            const covTotal = cov.total_shown || 0;
            const covColor = covPct >= 80 ? '#10b981' : covPct >= 50 ? '#eab308' : '#f43f5e';
            const covText = covTotal > 0 ? ` · Покрытие: ${covDecomp}/${covTotal} (${covPct}%)` : '';

            const allWords = [];
            for (const words of Object.values(data.results)) { allWords.push(...words); }
            const shownNote = (allWords.length < data.total) ? ` · <span style="color:#94a3b8;font-size:0.8em">показано ${allWords.length.toLocaleString('ru-RU')} из ${data.total.toLocaleString('ru-RU')}</span>` : '';

            msrchHeader.innerHTML = `${modeLabel} «${morpheme || '*'}» — ${data.total.toLocaleString('ru-RU')} (${sourceLabel})<span style="color:${covColor};font-size:0.85em">${covText}</span>${shownNote}`;

            // Download buttons
            const uncovered = data.uncovered || [];

            const _downloadFile = (filename, lines) => {
                const blob = new Blob([lines.join('\n')], {type: 'text/plain;charset=utf-8'});
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = filename;
                a.click();
                URL.revokeObjectURL(a.href);
            };

            let dlHtml = `<div style="margin:8px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap">` +
                `<button id="dl-all-btn" style="background:rgba(99,102,241,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8em">⬇ Все (${allWords.length})</button>`;
            if (uncovered.length > 0) {
                dlHtml += `<button id="dl-uncov-btn" style="background:rgba(244,63,94,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8em">⬇ Непокрытые (${uncovered.length})</button>`;
            }
            dlHtml += `</div>`;

            const posLabels = data.pos_labels || {};
            let html = dlHtml;

            for (const [type, words] of Object.entries(data.results)) {
                let color, border, label;
                if (isOpenCorpora) {
                    const pc = POS_COLORS[type] || { border: '#64748b', color: '#94a3b8' };
                    color = pc.color;
                    border = pc.border;
                    label = posLabels[type] || type;
                } else {
                    const tc = TYPE_COLORS[type] || TYPE_COLORS.root;
                    color = tc.color;
                    border = tc.border;
                    label = 'Как ' + (TYPE_LABELS[type] || type);
                }
                const sorted = [...words].sort((a, b) => a.localeCompare(b, 'ru'));
                html += `<div data-pos-group="${type}" style="margin-bottom: 20px;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 10px;">
                        <span style="font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: ${color};">${label}</span>
                        <span class="pos-group-count" style="font-size: 0.75rem; color: var(--text-secondary);">(${words.length})</span>
                    </div>
                    <div style="columns: 3; column-gap: 16px;">`;
                const mLower = morpheme.toLowerCase();
                const decomp = data.decomp || {};
                const MORPH_COLORS = {
                    PREFIX: '#818cf8',
                    ROOT: '#f87171',
                    SUFFIX: '#34d399',
                    ENDING: '#fbbf24',
                    LINK: '#f472b6'
                };
                sorted.forEach(w => {
                    let display;
                    const parts = decomp[w];
                    if (parts && parts.length > 0) {
                        display = parts.map(([t, v]) => {
                            const mc = MORPH_COLORS[t] || 'var(--text-primary)';
                            return `<span style="color: ${mc}; font-weight: ${t === 'ROOT' ? '700' : '500'};" title="${t}">${v}</span>`;
                        }).join('');
                    } else if (w.toLowerCase().endsWith(mLower)) {
                        const stem = w.slice(0, w.length - mLower.length);
                        display = `${stem}<span style="color: ${color}; font-weight: 600;">${w.slice(w.length - mLower.length)}</span>`;
                    } else {
                        display = w;
                    }
                    html += `<div class="msrch-word-item" data-word="${w.toLowerCase()}" style="break-inside: avoid; padding: 3px 0 3px 10px; margin-bottom: 2px; font-size: 0.85rem; color: var(--text-primary); border-left: 2px solid ${border};">${display}</div>`;
                });
                html += `</div></div>`;
            }

            msrchResultBox.innerHTML = html;
            msrchResultBox.classList.remove('empty');

            // Show word filter
            msrchFilterRow.style.display = 'block';
            if (!wordFilter) msrchWordFilter.value = '';

            // Attach download handlers
            const dlAllBtn = document.getElementById('dl-all-btn');
            if (dlAllBtn) dlAllBtn.addEventListener('click', () => _downloadFile(`all_${morpheme||'words'}.txt`, allWords));
            const dlUncovBtn = document.getElementById('dl-uncov-btn');
            if (dlUncovBtn) dlUncovBtn.addEventListener('click', () => _downloadFile(`uncovered_${morpheme||'words'}.txt`, uncovered));
        } catch (err) {
            console.error(err);
            msrchResultBox.innerHTML = '<div class="empty-state" style="color: var(--danger);">Ошибка связи с сервером.</div>';
        }
    }

    btnMsrch.addEventListener('click', () => _runMsrchSearch(msrchInput.value.trim(), ''));
    msrchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') btnMsrch.click(); });

    // Word filter — hybrid: client-side for Tikhonov, server-side for OpenCorpora
    let _wordFilterTimer = null;
    msrchWordFilter.addEventListener('input', () => {
        const q = msrchWordFilter.value.trim().toLowerCase();

        if (!useOpenCorpora) {
            // Client-side filtering (Tikhonov — small dataset)
            const items = msrchResultBox.querySelectorAll('.msrch-word-item');
            items.forEach(el => {
                const w = el.getAttribute('data-word') || '';
                el.style.display = (!q || w.includes(q)) ? '' : 'none';
            });
            msrchResultBox.querySelectorAll('[data-pos-group]').forEach(grp => {
                const vis = grp.querySelectorAll('.msrch-word-item:not([style*="display: none"])');
                const countEl = grp.querySelector('.pos-group-count');
                if (countEl) countEl.textContent = `(${vis.length})`;
                grp.style.display = vis.length === 0 ? 'none' : '';
            });
        } else {
            // Server-side filtering (OpenCorpora — debounced re-query)
            clearTimeout(_wordFilterTimer);
            _wordFilterTimer = setTimeout(() => {
                // Re-trigger search with word_filter
                _runMsrchSearch(msrchInput.value.trim(), q);
            }, 400);
        }
    });

    // Initial load
    loadRulesCatalog();
    loadCatalog();
});
