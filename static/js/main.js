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
    // Proper Noun Filtering Sync & Persistence
    // -----------------------------------------------------------------------
    const chkProperDec = document.getElementById('chk-proper-dec');
    const chkProperSearch = document.getElementById('chk-proper');

    const savedProper = localStorage.getItem('include_proper') === 'true';
    if (chkProperDec) chkProperDec.checked = savedProper;
    if (chkProperSearch) chkProperSearch.checked = savedProper;

    function syncProperCheckboxes(checked) {
        if (chkProperDec) chkProperDec.checked = checked;
        if (chkProperSearch) chkProperSearch.checked = checked;
        localStorage.setItem('include_proper', checked);
    }

    if (chkProperDec) {
        chkProperDec.addEventListener('change', (e) => {
            syncProperCheckboxes(e.target.checked);
            // Re-run decomposition if input exists
            const dInput = document.getElementById("dec-input-word");
            if (dInput \u0026\u0026 dInput.value.trim()) {
                document.getElementById('btn-run-decompose').click();
            }
        });
    }
    if (chkProperSearch) {
        chkProperSearch.addEventListener('change', (e) => {
            syncProperCheckboxes(e.target.checked);
            // Re-run search if input exists and the function is defined
            const msrchInput = document.getElementById('msrch-input');
            if (msrchInput \u0026\u0026 msrchInput.value.trim() \u0026\u0026 typeof _runMsrchSearch === 'function') {
                _runMsrchSearch(1);
            }
        });
    }

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
            const chkProperDec = document.getElementById('chk-proper-dec');
            const includeProper = chkProperDec && chkProperDec.checked;
            const data = await postData("/api/decompose", { word, include_proper: includeProper });
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
        try {
            const includeProper = chkProperDec \u0026\u0026 chkProperDec.checked;
            const data = await postData("/api/cognates", { word, include_proper: includeProper });
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
                html += `<div class="rule-card">
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

    const posLabels = {
        'NOUN': 'Существительное',
        'ADJF': 'Прилагательное',
        'VERB': 'Глагол',
        'INFN': 'Инфинитив',
        'PRTF': 'Причастие',
        'GRND': 'Деепричастие',
        'ADVB': 'Наречие',
        'ADJS': 'Краткое прил.',
        'PRTS': 'Краткое прич.',
        'COMP': 'Компаратив',
        'NUMR': 'Числительное',
        'any': 'Все'
    };

    // Global export functions
    window._downloadFile = (filename, lines) => {
        const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        window.URL.revokeObjectURL(url);
    };

    window._downloadExport = async (uncoveredOnly = false) => {
        if (!window._currentMsrchParams) return;
        const btnId = uncoveredOnly ? 'btn-download-uncovered' : 'btn-download-all';
        const btn = document.getElementById(btnId);
        const originalText = btn.textContent;
        btn.textContent = '⌛ ...';
        btn.disabled = true;

        try {
            const resp = await fetch('/api/ending_export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...window._currentMsrchParams, uncovered_only: uncoveredOnly })
            });
            if (resp.ok) {
                const blob = await resp.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${uncoveredOnly ? 'uncovered' : 'export'}_${window._currentMsrchParams.ending || 'words'}.txt`;
                a.click();
                window.URL.revokeObjectURL(url);
            } else {
                alert('Ошибка экспорта');
            }
        } catch (err) {
            console.error(err);
            alert('Ошибка сети');
        } finally {
            btn.textContent = originalText;
            btn.disabled = false;
        }
    };

    // Registry pagination helper
    window._registryPage = (page) => {
        const input = document.getElementById('msrch-input');
        input.value = '*';
        // Store page and trigger search
        window._registryRequestedPage = page;
        document.getElementById('btn-run-msrch').click();
    };

    // Registry download helper
    window._downloadRegistry = async (which) => {
        const mtype = window._currentRegistryType || 'root';
        const currentSource = window._currentRegistrySource || 'tikhonov';
        // Determine which source to download
        let source;
        if (which === 'other') {
            source = currentSource === 'tikhonov' ? 'opencorpora' : 'tikhonov';
        } else {
            source = currentSource;
        }
        try {
            let data;
            if (source === 'opencorpora') {
                data = await postData('/api/ending_search', {
                    ending: '*', search_type: mtype, pos: 'ANY',
                    page: 1, page_size: 0
                });
            } else {
                data = await postData('/api/morpheme_search', {
                    morpheme: '*', morpheme_type: mtype,
                    page: 1, page_size: 0
                });
            }
            if (data && data.results) {
                const items = Array.isArray(data.results) ? data.results : [];
                const exportData = items.map(m => ({
                    morpheme: typeof m === 'object' ? m.value : m,
                    example: typeof m === 'object' ? (m.example || '') : ''
                }));
                const json = JSON.stringify(exportData, null, 2);
                const blob = new Blob([json], {type: 'application/json'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `registry_${mtype}_${source}.json`;
                a.click();
                URL.revokeObjectURL(url);
            }
        } catch (e) {
            console.error(e);
            alert('Ошибка скачивания');
        }
    };

    // --- Theme Switcher ---
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
    let currentMsrchPage = 1;

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
    const btnSrcWiktionary = document.getElementById('btn-src-wiktionary');
    const btnSrcAlgorithmic = document.getElementById('btn-src-algorithmic');
    let useOpenCorpora = false;
    let useAlgorithmic = false;
    let activeSource = 'tikhonov';

    const posFilterGroup = document.getElementById('pos-filter-group');
    let activeEndPos = 'any';

    function _deactivateAllSrc() {
        btnSrcTikhonov.classList.remove('active');
        btnSrcOpenCorpora.classList.remove('active');
        btnSrcWiktionary.classList.remove('active');
        btnSrcAlgorithmic.classList.remove('active');
    }

    btnSrcTikhonov.addEventListener('click', () => {
        _deactivateAllSrc();
        btnSrcTikhonov.classList.add('active');
        useOpenCorpora = false;
        useAlgorithmic = false;
        activeSource = 'tikhonov';
        posFilterGroup.style.display = 'none';
        _runMsrchSearch(msrchInput.value.trim(), msrchWordFilter.value.trim(), 1);
    });
    btnSrcOpenCorpora.addEventListener('click', () => {
        _deactivateAllSrc();
        btnSrcOpenCorpora.classList.add('active');
        useOpenCorpora = true;
        useAlgorithmic = false;
        activeSource = 'algorithmic'; // for OpenCorpora (algorithmic decomp)
        posFilterGroup.style.display = 'block';
        _runMsrchSearch(msrchInput.value.trim(), msrchWordFilter.value.trim(), 1);
    });
    btnSrcWiktionary.addEventListener('click', () => {
        _deactivateAllSrc();
        btnSrcWiktionary.classList.add('active');
        useOpenCorpora = true; // Use the unified search endpoint
        useAlgorithmic = false;
        activeSource = 'wiktionary';
        posFilterGroup.style.display = 'block';
        _runMsrchSearch(msrchInput.value.trim(), msrchWordFilter.value.trim(), 1);
    });
    btnSrcAlgorithmic.addEventListener('click', () => {
        _deactivateAllSrc();
        btnSrcAlgorithmic.classList.add('active');
        useOpenCorpora = false;
        useAlgorithmic = true;
        activeSource = 'algorithmic_words';
        posFilterGroup.style.display = 'none';
        _loadAlgorithmic(1);
    });

    // Global helper: go back to registry (respects active source)
    window._goBackToRegistry = function() {
        document.getElementById('msrch-input').value = '*';
        if (useAlgorithmic) {
            _loadAlgorithmic(1);
        } else {
            document.getElementById('btn-run-msrch').click();
        }
    };

    // Algorithmic decomposition viewer
    async function _loadAlgorithmic(page = 1) {
        msrchResultBox.innerHTML = '<div class="empty-state">Загрузка...</div>';
        document.getElementById('msrch-actions-bar').style.display = 'none';
        try {
            // If specific type selected → show registry (like Tikhonov)
            if (activeMsrchType !== 'any') {
                const data = await postData('/api/algorithmic_registry', {
                    morpheme_type: activeMsrchType,
                    page: 1,
                    page_size: 5000
                });
                if (!data || !data.results || data.results.length === 0) {
                    msrchResultBox.innerHTML = '<div class="empty-state">Нет данных</div>';
                    msrchHeader.textContent = 'OpenCorpora — пусто';
                    return;
                }
                const label = data.type === 'PREFIX' ? 'приставки' : data.type === 'SUFFIX' ? 'суффиксы' : data.type === 'ROOT' ? 'корни' : data.type === 'ENDING' ? 'окончания' : data.type;
                msrchHeader.innerHTML = `<div class="msrch-results-header">
                    <span style="color:var(--text-secondary)">OpenCorpora</span>
                    <span style="color:var(--text-secondary)">/</span>
                    <span style="font-weight:700">${label}</span>
                    <span style="font-size:0.85rem; color:var(--text-secondary); margin-left:auto;">${data.total.toLocaleString('ru-RU')} ед.</span>
                </div>`;

                const actionsBar = document.getElementById('msrch-actions-bar');
                actionsBar.innerHTML = `<div style="margin:4px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                    <button onclick="_downloadAlgoRegistry()" style="background:rgba(34,197,94,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;">⬇ OpenCorpora (${data.total.toLocaleString('ru-RU')})</button>
                </div>`;
                actionsBar.style.display = 'block';

                let uHtml = '<div class="msrch-registry-grid">';
                data.results.forEach(m => {
                    const mVal = typeof m === 'object' ? m.value : m;
                    const mCount = typeof m === 'object' ? m.count : 0;
                    uHtml += `<div class="msrch-registry-item" style="border-left-color:#22c55e;" onclick="document.getElementById('msrch-input').value='${mVal}'; document.getElementById('btn-run-msrch').click();">
                        <span class="msrch-registry-val">${mVal}</span>
                        <span class="msrch-registry-count">${mCount.toLocaleString('ru-RU')}</span>
                    </div>`;
                });
                uHtml += '</div>';
                msrchResultBox.innerHTML = uHtml;
                return;
            }

            // 'any' mode → show word list with decomposition
            const data = await postData('/api/algorithmic_words', {
                morpheme_type: 'any',
                page: page,
                page_size: 200
            });
            if (!data || !data.results || data.results.length === 0) {
                msrchResultBox.innerHTML = '<div class="empty-state">Нет данных</div>';
                msrchHeader.textContent = 'OpenCorpora — пусто';
                return;
            }
            const pg = data.pagination;
            msrchHeader.innerHTML = `<div class="msrch-results-header">
                <span style="color:var(--text-secondary)">OpenCorpora</span>
                <span style="color:var(--text-secondary)">/</span>
                <span style="font-weight:700">Все разобранные</span>
                <span style="font-size:0.85rem;color:var(--text-secondary);margin-left:auto;">${data.total.toLocaleString('ru-RU')} слов</span>
            </div>
            <div style="display:flex;gap:10px;align-items:center;font-size:0.75rem;margin:4px 0;flex-wrap:wrap;">
                <span><span style="color:#60a5fa;font-weight:700">■</span> приставка</span>
                <span><span style="color:#f87171;font-weight:700">■</span> корень</span>
                <span><span style="color:#4ade80;font-weight:700">■</span> суффикс</span>
                <span><span style="color:#fbbf24;font-weight:700">■</span> окончание</span>
                <span><span style="color:#94a3b8;font-weight:700">■</span> интерфикс</span>
            </div>`;

            const typeColors = {
                PREFIX: '#60a5fa', ROOT: '#f87171', SUFFIX: '#4ade80',
                ENDING: '#fbbf24', LINK: '#94a3b8'
            };

            let html = '<div style="display:flex;flex-direction:column;gap:3px;">';
            for (const item of data.results) {
                let morphHtml = '';
                for (const m of item.morphemes) {
                    const c = typeColors[m.type] || '#888';
                    morphHtml += `<span style="color:${c};font-weight:600;border-bottom:2px solid ${c};padding:0 2px;">${m.value}</span>`;
                    morphHtml += '<span style="color:var(--text-secondary);opacity:0.3">·</span>';
                }
                morphHtml = morphHtml.replace(/·<\/span>$/, '</span>');
                html += `<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:6px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);">
                    <span style="min-width:140px;font-weight:500;color:var(--text-primary);font-size:0.9rem;">${item.lemma}</span>
                    <span style="font-size:0.85rem;">${morphHtml}</span>
                </div>`;
            }
            html += '</div>';

            // Download + Pagination controls → actions bar
            const actionsBar2 = document.getElementById('msrch-actions-bar');
            let abHtml = `<div style="margin:4px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap;">`;
            abHtml += `<button onclick="_downloadAlgorithmic()" style="background:rgba(34,197,94,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;">⬇ JSON (${data.total.toLocaleString('ru-RU')})</button>`;
            if (pg && pg.total_pages > 1) {
                abHtml += `<span style="margin-left:auto;display:flex;gap:4px;align-items:center;">`;
                if (pg.page > 1) {
                    abHtml += `<button onclick="_loadAlgorithmic(${pg.page - 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">← Назад</button>`;
                }
                abHtml += `<span style="color:var(--text-secondary);font-size:0.8rem;">${pg.page}/${pg.total_pages}</span>`;
                if (pg.page < pg.total_pages) {
                    abHtml += `<button onclick="_loadAlgorithmic(${pg.page + 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">Далее →</button>`;
                }
                abHtml += '</span>';
            }
            abHtml += '</div>';
            actionsBar2.innerHTML = abHtml;
            actionsBar2.style.display = 'block';

            msrchResultBox.innerHTML = html;
        } catch (e) {
            console.error(e);
            msrchResultBox.innerHTML = '<div class="empty-state">Ошибка загрузки</div>';
        }
    }
    window._loadAlgorithmic = _loadAlgorithmic;

    async function _downloadAlgorithmic() {
        try {
            const data = await postData('/api/algorithmic_words', {
                morpheme_type: activeMsrchType,
                page: 1,
                page_size: 0
            });
            if (data && data.results) {
                const exportData = data.results.map(item => ({
                    lemma: item.lemma,
                    morphemes: item.morphemes.map(m => m.value).join('·'),
                    decomposition: item.morphemes.map(m => ({[m.type.toLowerCase()]: m.value}))
                }));
                const json = JSON.stringify(exportData, null, 2);
                const blob = new Blob([json], {type: 'application/json'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `algorithmic_${activeMsrchType}.json`;
                a.click();
                URL.revokeObjectURL(url);
            }
        } catch (e) {
            console.error(e);
            alert('Ошибка скачивания');
        }
    }
    window._downloadAlgorithmic = _downloadAlgorithmic;

    async function _downloadAlgoRegistry() {
        try {
            const data = await postData('/api/algorithmic_registry', {
                morpheme_type: activeMsrchType,
                page: 1,
                page_size: 0
            });
            if (data && data.results) {
                const exportData = data.results.map(m => ({
                    morpheme: m.value,
                    example: m.example || ''
                }));
                const json = JSON.stringify(exportData, null, 2);
                const blob = new Blob([json], {type: 'application/json'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `algorithmic_${activeMsrchType}_registry.json`;
                a.click();
                URL.revokeObjectURL(url);
            }
        } catch (e) {
            console.error(e);
            alert('Ошибка скачивания');
        }
    }
    window._downloadAlgoRegistry = _downloadAlgoRegistry;

    // POS filter buttons
    const endPosBtns = document.querySelectorAll('#pos-filter-group [data-pos]');
    endPosBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            endPosBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeEndPos = btn.dataset.pos;
            _runMsrchSearch(msrchInput.value.trim(), msrchWordFilter.value.trim(), 1);
        });
    });

    // Morpheme type buttons
    [msrchBtns.any, msrchBtns.prefix, msrchBtns.suffix, msrchBtns.ending, msrchBtns.root].forEach(btn => {
        btn.addEventListener('click', () => {
            msrchInput.value = ''; // Clear input on type switch
            Object.values(msrchBtns).forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeMsrchType = btn.id.replace('btn-msrch-', '');
            
            // Clear filter row too
            msrchWordFilter.value = '';
            
            // Automatically trigger registry view (*)
            if (useAlgorithmic) {
                _loadAlgorithmic(1);
            } else {
                _runMsrchSearch('*', '', 1);
            }
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



    const chkNoLimit = document.getElementById('chk-no-limit');

    async function _runMsrchSearch(morpheme, wordFilter, page = 1) {
        currentMsrchPage = page;
        msrchResultBox.innerHTML = '<div class="empty-state">Поиск...</div>';
        document.getElementById('msrch-actions-bar').style.display = 'none';

        const isOpenCorpora = useOpenCorpora;
        const noLimit = chkNoLimit && chkNoLimit.checked;
        const includeProper = document.getElementById('chk-proper') && document.getElementById('chk-proper').checked;

        try {
            let data;
            if (isOpenCorpora) {
                const stMap = { any: 'any', prefix: 'prefix', suffix: 'suffix', ending: 'ending', root: 'root' };
                const searchType = stMap[activeMsrchType] || 'ending';
                const params = {
                    ending: morpheme,
                    pos: activeEndPos,
                    search_type: searchType,
                    page: currentMsrchPage,
                    page_size: noLimit ? 0 : 5000,
                    include_proper: includeProper,
                    source: activeSource
                };
                if (wordFilter) params.word_filter = wordFilter;
                data = await postData('/api/ending_search', params);
            } else {
                data = await postData('/api/morpheme_search', { 
                    morpheme, 
                    morpheme_type: activeMsrchType, 
                    page: currentMsrchPage, 
                    page_size: 5000, 
                    source: activeSource,
                    include_proper: includeProper 
                });
            }

            if (data.total === 0) {
                msrchResultBox.innerHTML = `<div class="empty-state">«${morpheme}» не найдено</div>`;
                msrchHeader.textContent = 'Ничего не найдено';
                return;
            }

            if (data.only_unique) {
                const label = data.type === 'PREFIX' ? 'приставки' : data.type === 'SUFFIX' ? 'суффиксы' : data.type === 'ROOT' ? 'корни' : data.type === 'ENDING' ? 'окончания' : data.type;
                const sourceLabel = isOpenCorpora ? 'OpenCorpora' : 'Тихонов';
                
                // Fetch opposite source for diff (only for prefix/suffix/ending, skip root — too large)
                let otherSet = null;
                const diffTypes = ['prefix', 'suffix', 'ending'];
                if (diffTypes.includes(activeMsrchType)) {
                    try {
                        let otherData;
                        if (isOpenCorpora) {
                            otherData = await postData('/api/morpheme_search', { morpheme: '*', morpheme_type: activeMsrchType, page: 1, page_size: 0 });
                        } else {
                            otherData = await postData('/api/ending_search', { ending: '*', search_type: activeMsrchType, pos: 'ANY', page: 1, page_size: 0 });
                        }
                        if (otherData && otherData.results) {
                            const items = Array.isArray(otherData.results) ? otherData.results : [];
                            otherSet = new Set(items.map(m => typeof m === 'object' ? m.value : m));
                        }
                    } catch(e) { /* ignore diff errors */ }
                }
                
                // Count diff
                let diffCount = 0;
                let bothCount = 0;
                if (otherSet) {
                    data.results.forEach(m => {
                        const val = typeof m === 'object' ? m.value : m;
                        if (otherSet.has(val)) bothCount++;
                        else diffCount++;
                    });
                }
                
                // Pagination info
                let pgInfo = '';
                const pg = data.pagination;
                if (pg && pg.total_pages > 1) {
                    const startIdx = (pg.page - 1) * pg.page_size + 1;
                    const endIdx = startIdx + pg.shown - 1;
                    pgInfo = ` · <span style="color:#94a3b8;font-size:0.8rem;">стр. ${pg.page} из ${pg.total_pages} (${startIdx.toLocaleString('ru-RU')}–${endIdx.toLocaleString('ru-RU')})</span>`;
                }
                
                const otherLabel = isOpenCorpora ? 'Тихонов' : 'OpenCorpora';
                let diffLegend = '';
                if (otherSet) {
                    diffLegend = `<div style="display:flex;gap:12px;align-items:center;font-size:0.8rem;margin:6px 0;flex-wrap:wrap;">
                        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#9a59f6;display:inline-block;"></span> в обоих (${bothCount})</span>
                        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:#f59e0b;display:inline-block;"></span> только ${sourceLabel} (${diffCount})</span>
                    </div>`;
                }
                
                msrchHeader.innerHTML = `<div class="msrch-results-header">
                    <span style="color:var(--text-secondary)">Реестр</span>
                    <span style="color:var(--text-secondary)">/</span>
                    <span style="font-weight:700">${label}</span>
                    <span style="font-size:0.85rem; color:var(--text-secondary); margin-left:auto;">${data.total.toLocaleString('ru-RU')} ед.</span>
                    ${pgInfo}
                </div>${diffLegend}`;
                
                // Download + pagination controls → actions bar
                const otherCount = otherSet ? otherSet.size : 0;
                let controlsHtml = `<div style="margin:4px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap">`;
                controlsHtml += `<button onclick="_downloadRegistry('current')" style="background:rgba(99,102,241,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;">⬇ ${sourceLabel} (${data.total.toLocaleString('ru-RU')})</button>`;
                if (otherSet) {
                    controlsHtml += `<button onclick="_downloadRegistry('other')" style="background:rgba(245,158,11,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8rem;">⬇ ${otherLabel} (${otherCount.toLocaleString('ru-RU')})</button>`;
                }
                
                if (pg && pg.total_pages > 1) {
                    controlsHtml += `<span style="margin-left:auto;display:flex;gap:4px;align-items:center;">`;
                    if (pg.page > 1) {
                        controlsHtml += `<button onclick="_registryPage(${pg.page - 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">← Назад</button>`;
                    }
                    controlsHtml += `<span style="color:var(--text-secondary);font-size:0.8rem;">${pg.page}/${pg.total_pages}</span>`;
                    if (pg.page < pg.total_pages) {
                        controlsHtml += `<button onclick="_registryPage(${pg.page + 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">Далее →</button>`;
                    }
                    controlsHtml += `</span>`;
                }
                controlsHtml += `</div>`;
                
                const regActionsBar = document.getElementById('msrch-actions-bar');
                regActionsBar.innerHTML = controlsHtml;
                regActionsBar.style.display = 'block';

                let uHtml = `<div class="msrch-registry-grid">`;
                data.results.forEach(m => {
                    const mVal = typeof m === 'object' ? m.value : m;
                    const mCount = typeof m === 'object' ? m.count : 0;
                    const isUnique = otherSet && !otherSet.has(mVal);
                    const borderColor = isUnique ? '#f59e0b' : '#9a59f6';
                    const bgColor = isUnique ? 'rgba(245,158,11,0.08)' : '';
                    
                    uHtml += `<div class="msrch-registry-item" style="border-left-color:${borderColor};${bgColor ? 'background:' + bgColor + ';' : ''}" onclick="document.getElementById('msrch-input').value='${mVal}'; document.getElementById('btn-run-msrch').click();">
                        <span class="msrch-registry-val">${mVal}</span>
                        <span class="msrch-registry-count">${mCount.toLocaleString('ru-RU')}</span>
                    </div>`;
                });
                uHtml += `</div>`;
                
                // Bottom pagination
                if (pg && pg.total_pages > 1) {
                    uHtml += `<div style="margin:12px 0;display:flex;gap:6px;justify-content:center;align-items:center;">`;
                    if (pg.page > 1) {
                        uHtml += `<button onclick="_registryPage(${pg.page - 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">← Назад</button>`;
                    }
                    uHtml += `<span style="color:var(--text-secondary);font-size:0.8rem;">${pg.page}/${pg.total_pages}</span>`;
                    if (pg.page < pg.total_pages) {
                        uHtml += `<button onclick="_registryPage(${pg.page + 1})" style="background:rgba(255,255,255,0.05);border:1px solid var(--border-color);color:var(--text-primary);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:0.8rem;">Далее →</button>`;
                    }
                    uHtml += `</div>`;
                }
                
                msrchResultBox.innerHTML = uHtml;
                msrchResultBox.classList.remove('empty');
                msrchFilterRow.style.display = 'none';
                
                // Store registry context for download/pagination
                window._currentRegistryType = activeMsrchType;
                window._currentRegistrySource = isOpenCorpora ? 'opencorpora' : 'tikhonov';
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

            // Coverage stats (global for OpenCorpora if total < 20k)
            const currentTotalWords = data.total || 0;
            const totalUncovered = data.uncovered_only_total; // -1 if not calculated (too many)
            let covText = '';
            let covColor = '#94a3b8';
            
            if (totalUncovered !== undefined && totalUncovered !== -1 && totalUncovered <= currentTotalWords) {
                const totalDecomp = currentTotalWords - totalUncovered;
                const totalPct = currentTotalWords > 0 ? Math.round(100 * totalDecomp / currentTotalWords) : 0;
                covColor = totalPct >= 80 ? '#10b981' : totalPct >= 50 ? '#eab308' : '#f43f5e';
                covText = ` · Покрытие: ${totalDecomp.toLocaleString('ru-RU')}/${currentTotalWords.toLocaleString('ru-RU')} (${totalPct}%)`;
            } else if (currentTotalWords > 0) {
                covText = ` · Всего: ${currentTotalWords.toLocaleString('ru-RU')} слов`;
            }

            const allWords = [];
            for (const words of Object.values(data.results)) { allWords.push(...words); }
            
            // Pagination info in header
            let pgInfo = '';
            const pg = data.pagination;
            if (pg && pg.total_pages > 1) {
                const startIdx = (pg.page - 1) * pg.page_size + 1;
                const endIdx = startIdx + pg.shown - 1;
                pgInfo = ` · <span style="color:#94a3b8;font-size:0.8em">стр. ${pg.page} из ${pg.total_pages} (слова ${startIdx.toLocaleString('ru-RU')}–${endIdx.toLocaleString('ru-RU')})</span>`;
            } else {
                const shownNote = (allWords.length < data.total) ? ` · <span style="color:#94a3b8;font-size:0.8em">показано ${allWords.length.toLocaleString('ru-RU')} из ${data.total.toLocaleString('ru-RU')}</span>` : '';
                pgInfo = shownNote;
            }

            const isRegistryBack = (morpheme && morpheme !== '*' && activeMsrchType !== 'any');
            const label = activeMsrchType === 'prefix' ? 'приставки' : activeMsrchType === 'suffix' ? 'суффиксы' : 'корни';
            
            let headerHtml = `<div class="msrch-results-header">`;
            if (isRegistryBack) {
                headerHtml += `
                    <button onclick="_goBackToRegistry()" class="msrch-back-btn">←</button>
                    <div style="display: flex; align-items: center; gap: 6px; font-size: 0.9rem;">
                        <span style="color:var(--text-secondary); opacity: 0.7;">Реестр</span>
                        <span style="color:var(--text-secondary); opacity: 0.5;">/</span>
                        <span style="color:var(--text-secondary); cursor:pointer; opacity: 0.8;" onclick="_goBackToRegistry()">${label}</span>
                        <span style="color:var(--text-secondary); opacity: 0.5;">/</span>
                        <span style="font-weight:700; color: var(--text-primary);">«${morpheme}»</span>
                    </div>
                `;
            } else {
                headerHtml += `<span style="font-weight:700; font-size: 1.1rem; color: var(--text-primary);">${modeLabel} «${morpheme || '*'}»</span>`;
            }
            headerHtml += `<span style="color:var(--text-secondary); margin-left:12px; font-weight: 500;">— ${data.total.toLocaleString('ru-RU')}</span>`;
            headerHtml += `<span style="color:${covColor}; font-size:0.85rem; margin-left:12px; background: rgba(255,255,255,0.03); padding: 2px 10px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">${covText}</span>`;
            headerHtml += pgInfo;
            headerHtml += `</div>`;

            msrchHeader.innerHTML = headerHtml;

            // Store params for export
            window._currentMsrchParams = {
                ending: morpheme,
                pos: activeEndPos,
                search_type: activeMsrchType,
                word_filter: wordFilter,
                search_source: isOpenCorpora ? 'opencorpora' : 'tikhonov',
                include_proper: includeProper
            };

            const uncLabel = (totalUncovered !== undefined && totalUncovered !== -1) ? totalUncovered.toLocaleString('ru-RU') : '...';

            const actionsBar = document.getElementById('msrch-actions-bar');
            actionsBar.innerHTML = `<div style="margin:4px 0;display:flex;gap:6px;align-items:center;flex-wrap:wrap">` +
                `<button id="btn-download-all" onclick="_downloadExport(false)" style="background:rgba(99,102,241,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8em">⬇ Все (${currentTotalWords.toLocaleString('ru-RU')})</button>` +
                `<button id="btn-download-uncovered" onclick="_downloadExport(true)" style="background:rgba(244,63,94,0.7);border:none;color:#fff;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:0.8em">⬇ Непокрытые (${uncLabel})</button>` +
                `</div>`;
            actionsBar.style.display = 'block';

            let html = '';

            // Top pagination
            let pgHtml = '';
            if (pg && pg.total_pages > 1) {
                pgHtml = `<div class="pagination-controls" style="margin: 15px 0; display: flex; gap: 6px; justify-content: center; align-items: center; flex-wrap: wrap;">`;
                if (pg.page > 1) pgHtml += `<button class="pg-btn" data-page="${pg.page - 1}" style="background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em;">←</button>`;
                const start = Math.max(1, pg.page - 3);
                const end = Math.min(pg.total_pages, pg.page + 3);
                if (start > 1) {
                    pgHtml += `<button class="pg-btn" data-page="1" style="background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em;">1</button>`;
                    if (start > 2) pgHtml += `<span style="color: var(--text-secondary)">...</span>`;
                }
                for (let i = start; i <= end; i++) {
                    const isActive = i === pg.page;
                    const style = isActive ? `background: var(--primary-color); color: #fff; border: 1px solid var(--primary-color);` : `background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary);`;
                    pgHtml += `<button class="pg-btn" data-page="${i}" style="${style} padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em;">${i}</button>`;
                }
                if (end < pg.total_pages) {
                    if (end < pg.total_pages - 1) pgHtml += `<span style="color: var(--text-secondary)">...</span>`;
                    pgHtml += `<button class="pg-btn" data-page="${pg.total_pages}" style="background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em;">${pg.total_pages}</button>`;
                }
                if (pg.page < pg.total_pages) pgHtml += `<button class="pg-btn" data-page="${pg.page + 1}" style="background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-primary); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85em;">→</button>`;
                pgHtml += `</div>`;
                html += pgHtml;
            }

            // Morpheme stats summary
            if (data.morpheme_stats) {
                const stats = data.morpheme_stats;
                const m_type_map = { prefix: 'PREFIX', suffix: 'SUFFIX', root: 'ROOT', any: 'PREFIX' };
                const t = m_type_map[activeMsrchType] || 'PREFIX';
                
                // Show companion roots (second roots in compound words)
                if (stats['COMPANION_ROOT']) {
                    const compList = Object.entries(stats['COMPANION_ROOT']).sort((a, b) => b[1] - a[1]);
                    if (compList.length > 0) {
                        html += `<div class="msrch-summary-box">`;
                        html += `<div class="msrch-summary-title">Корни-спутники (в составных словах):</div>`;
                        html += `<div class="msrch-registry-grid" style="padding:0">`;
                        compList.slice(0, 80).forEach(([val, count]) => {
                            html += `<div class="msrch-registry-item" onclick="document.getElementById('msrch-word-filter').value='${val}'; document.getElementById('msrch-word-filter').dispatchEvent(new Event('input'))">` +
                                    `<span class="msrch-registry-val" style="font-size:0.85rem">${val}</span>` +
                                    `<span class="msrch-registry-count">${count.toLocaleString('ru-RU')}</span>` +
                                    `</div>`;
                        });
                        html += `</div></div>`;
                    }
                }
                
                if (stats[t]) {
                    const mList = Object.entries(stats[t]).sort((a, b) => b[1] - a[1]);
                    if (mList.length > 0) {
                        html += `<div class="msrch-summary-box">`;
                        const label = t === 'PREFIX' ? 'приставки' : t === 'SUFFIX' ? 'суффиксы' : 'корни';
                        html += `<div class="msrch-summary-title">Обнаруженные ${label}:</div>`;
                        html += `<div class="msrch-registry-grid" style="padding:0">`;
                        mList.slice(0, 120).forEach(([val, count]) => {
                            html += `<div class="msrch-registry-item" onclick="document.getElementById('msrch-word-filter').value='${val}'; document.getElementById('msrch-word-filter').dispatchEvent(new Event('input'))">` +
                                    `<span class="msrch-registry-val" style="font-size:0.85rem">${val}</span>` +
                                    `<span class="msrch-registry-count">${count.toLocaleString('ru-RU')}</span>` +
                                    `</div>`;
                        });
                        html += `</div></div>`;
                    }
                }
            }

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
                html += `<div data-pos-group="${type}" class="pos-group">
                    <div class="pos-group-header">
                        <span class="pos-group-label" style="color: ${color};">${label}</span>
                        <span class="pos-group-count">${words.length.toLocaleString('ru-RU')}</span>
                    </div>
                    <div class="msrch-word-list">`;
                const mLower = morpheme.toLowerCase();
                const decomp = data.decomp || {};
                // Map search type to DB mtype for highlighting
                const HIGHLIGHT_TYPE_MAP = {
                    'suffix': 'SUFFIX', 'prefix': 'PREFIX', 'root': 'ROOT',
                    'ending': 'ENDING', 'compound_root': 'ROOT'
                };
                // For OpenCorpora, `type` is POS (Существительное etc), not morpheme type
                // Use activeMsrchType which is the actual search tab (root/suffix/prefix/ending)
                const highlightMtype = HIGHLIGHT_TYPE_MAP[activeMsrchType] || HIGHLIGHT_TYPE_MAP[type] || '';
                    sorted.forEach(w => {
                        let display;
                        // Handle reflexive grouping: впускать(ся) → decompose 'впускать', show '(ся)' suffix
                        let baseWord = w;
                        let reflexiveSuffix = '';
                        if (w.endsWith('(ся)')) {
                            baseWord = w.slice(0, -4);
                            reflexiveSuffix = '<span style="color:var(--text-secondary);font-weight:400">(ся)</span>';
                        }
                        const parts = decomp[baseWord] || decomp[w];
                        if (parts && parts.length > 0) {
                            // Only underline the part matching the active search type + morpheme value
                            display = parts.map(([t, v]) => {
                                // For ROOT: partial match (root forms vary: добыв/добыва)
                                // For others: exact match
                                const vLow = v.toLowerCase();
                                const isMatch = t === highlightMtype && (
                                    vLow === mLower || vLow.includes(mLower) || mLower.includes(vLow)
                                );
                                if (isMatch) {
                                    return `<span style="color: ${color}; font-weight: 700; text-decoration: underline; text-decoration-color: ${color}; text-underline-offset: 3px;" title="${t}">${v}</span>`;
                                }
                                return `<span title="${t}">${v}</span>`;
                            }).join('') + reflexiveSuffix;
                        } else if (baseWord.toLowerCase().includes(mLower)) {
                            // Fallback: highlight substring
                            const idx = baseWord.toLowerCase().indexOf(mLower);
                            if (idx >= 0) {
                                const before = baseWord.slice(0, idx);
                                const match = baseWord.slice(idx, idx + mLower.length);
                                const after = baseWord.slice(idx + mLower.length);
                                display = `${before}<span style="color: ${color}; font-weight: 700; text-decoration: underline; text-decoration-color: ${color}; text-underline-offset: 3px;">${match}</span>${after}${reflexiveSuffix}`;
                            } else {
                                display = w;
                            }
                        } else {
                            display = w;
                        }
                        
                        if (isOpenCorpora) {
                            html += `<div class="msrch-word-item-premium" data-word="${baseWord.toLowerCase()}" style="border-left: 3px solid ${border};">${display}</div>`;
                        } else {
                            html += `<div class="msrch-word-item-classic" data-word="${baseWord.toLowerCase()}" style="border-left-color: ${border};">${display}</div>`;
                        }
                    });
                html += `</div></div>`;
            }

            // Bottom pagination
            if (pgHtml) {
                html += pgHtml.replace('margin: 15px 0', 'margin-top: 30px; padding: 20px 0; border-top: 1px solid var(--border-color)');
            }

            msrchResultBox.innerHTML = html;
            msrchResultBox.classList.remove('empty');

            // Attach pagination handlers
            msrchResultBox.querySelectorAll('.pg-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const p = parseInt(btn.dataset.page);
                    _runMsrchSearch(morpheme, wordFilter, p);
                    msrchResultBox.parentElement.scrollTop = 0; // scroll up result box
                });
            });

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

    btnMsrch.addEventListener('click', () => _runMsrchSearch(msrchInput.value.trim(), '', 1));
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
                // Re-trigger search with word_filter, reset to page 1
                _runMsrchSearch(msrchInput.value.trim(), q, 1);
            }, 400);
        }
    });

    // Initial load
    loadRulesCatalog();
    loadCatalog();
});
