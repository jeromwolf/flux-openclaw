/* flux-openclaw 대시보드 SPA */
(function () {
    'use strict';

    // ---- API 헬퍼 ----
    async function api(path, options) {
        options = options || {};
        var token = sessionStorage.getItem('dashboard_token') || '';
        var res = await fetch('/api' + path, {
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            },
            ...options,
        });
        if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
        return res.json();
    }

    // ---- 토스트 알림 ----
    function showToast(message, type) {
        type = type || 'info';
        var container = document.getElementById('toast-container');
        var el = document.createElement('div');
        el.className = 'toast ' + type;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(function () {
            el.classList.add('fade-out');
            setTimeout(function () { el.remove(); }, 350);
        }, 3000);
    }

    // ---- 로딩 상태 ----
    function setLoading(visible) {
        var el = document.getElementById('loading');
        el.classList.toggle('visible', visible);
        document.getElementById('page-content').style.display = visible ? 'none' : '';
    }

    // ---- 토큰 관리 ----
    var tokenInput = document.getElementById('token-input');
    var tokenSave = document.getElementById('token-save');

    tokenInput.value = sessionStorage.getItem('dashboard_token') || '';
    tokenSave.addEventListener('click', function () {
        sessionStorage.setItem('dashboard_token', tokenInput.value.trim());
        showToast('토큰이 저장되었습니다.', 'success');
        navigateTo(currentSection());
    });

    // ---- 사이드바 토글 (모바일) ----
    document.getElementById('sidebar-toggle').addEventListener('click', function () {
        document.getElementById('sidebar').classList.toggle('open');
    });

    // ---- 라우팅 ----
    var sections = ['status', 'tools', 'memory', 'schedules', 'knowledge', 'usage'];
    var refreshTimer = null;

    function currentSection() {
        var hash = location.hash.replace('#', '');
        return sections.indexOf(hash) >= 0 ? hash : 'status';
    }

    function navigateTo(section) {
        if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
        // 사이드바 활성 표시
        document.querySelectorAll('.nav-item').forEach(function (el) {
            el.classList.toggle('active', el.getAttribute('data-section') === section);
        });
        // 모바일 사이드바 닫기
        document.getElementById('sidebar').classList.remove('open');
        // 페이지 제목 갱신
        var titles = { status: '상태', tools: '도구', memory: '메모리', schedules: '스케줄', knowledge: '지식', usage: '사용량' };
        document.getElementById('page-title').textContent = titles[section] || section;
        // 렌더링
        var renderers = {
            status: renderStatus,
            tools: renderTools,
            memory: renderMemory,
            schedules: renderSchedules,
            knowledge: renderKnowledge,
            usage: renderUsage,
        };
        if (renderers[section]) renderers[section]();
    }

    window.addEventListener('hashchange', function () { navigateTo(currentSection()); });

    // ---- 상태 페이지 ----
    async function renderStatus() {
        setLoading(true);
        try {
            var d = await api('/status');
            var svcHtml = Object.keys(d.services || {}).map(function (k) {
                var ok = d.services[k];
                return '<tr><td><span class="status-dot ' + (ok ? 'green' : 'red') + '"></span>' + esc(k) + '</td><td>' + (ok ? '활성' : '중지') + '</td></tr>';
            }).join('');
            var toolsList = (d.tool_names || []).map(function (n) { return '<code>' + esc(n) + '</code>'; }).join(', ') || '<span class="text-muted">없음</span>';
            var memStats = d.memory_stats || {};
            var catHtml = '';
            if (memStats.categories) {
                catHtml = Object.keys(memStats.categories).map(function (c) {
                    return '<span class="text-muted">' + esc(c) + ': ' + memStats.categories[c] + '</span>';
                }).join(' &middot; ');
            }
            document.getElementById('page-content').innerHTML =
                '<div class="grid-3">' +
                    '<div class="card"><div class="stat-value">' + formatUptime(d.uptime_seconds) + '</div><div class="stat-label">업타임</div></div>' +
                    '<div class="card"><div class="stat-value">' + (d.tools_loaded || 0) + '</div><div class="stat-label">로드된 도구</div></div>' +
                    '<div class="card"><div class="stat-value">' + (memStats.total_memories || 0) + '</div><div class="stat-label">메모리 항목</div></div>' +
                '</div>' +
                '<div class="card"><div class="card-title">서비스 상태</div><table><thead><tr><th>서비스</th><th>상태</th></tr></thead><tbody>' + svcHtml + '</tbody></table></div>' +
                '<div class="card"><div class="card-title">로드된 도구</div><p>' + toolsList + '</p></div>' +
                (catHtml ? '<div class="card"><div class="card-title">메모리 카테고리</div><p>' + catHtml + '</p></div>' : '') +
                '<p class="text-muted mt-1">서버 시작: ' + esc(d.server_start || '') + ' &mdash; 현재: ' + esc(d.current_time || '') + '</p>';
            setLoading(false);
            // 30초 자동 새로고침
            refreshTimer = setInterval(renderStatus, 30000);
        } catch (e) {
            setLoading(false);
            showToast('상태 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">상태를 불러올 수 없습니다.</p>';
        }
    }

    function formatUptime(sec) {
        if (!sec) return '0초';
        var h = Math.floor(sec / 3600);
        var m = Math.floor((sec % 3600) / 60);
        if (h > 0) return h + '시간 ' + m + '분';
        if (m > 0) return m + '분';
        return Math.floor(sec) + '초';
    }

    // ---- 도구 페이지 ----
    async function renderTools() {
        setLoading(true);
        try {
            var data = await api('/tools');
            var rows = (data.tools || []).map(function (t) {
                return '<tr><td><strong>' + esc(t.name) + '</strong></td><td>' + esc(t.description) + '</td></tr>';
            }).join('');
            var mpHtml = '';
            try {
                var mp = await api('/tools/marketplace');
                var mpRows = (mp.tools || []).map(function (t) {
                    var name = t.name || t.tool_name || '';
                    var installed = t.installed || false;
                    var btn = installed
                        ? '<button class="btn-danger" onclick="window._mpAction(\'uninstall\',\'' + esc(name) + '\')">\uc81c\uac70</button>'
                        : '<button class="btn-primary btn-sm" onclick="window._mpAction(\'install\',\'' + esc(name) + '\')">\uc124\uce58</button>';
                    return '<tr><td>' + esc(name) + '</td><td>' + esc(t.description || '') + '</td><td>' + btn + '</td></tr>';
                }).join('');
                if (mpRows) {
                    mpHtml = '<div class="card mt-1"><div class="card-title">마켓플레이스</div>' +
                        '<table><thead><tr><th>이름</th><th>설명</th><th>작업</th></tr></thead><tbody>' + mpRows + '</tbody></table></div>';
                }
            } catch (_) { /* 마켓플레이스 미사용 */ }
            document.getElementById('page-content').innerHTML =
                '<div class="card"><div class="card-title">로드된 도구 (' + (data.count || 0) + '개)</div>' +
                (rows ? '<table><thead><tr><th>이름</th><th>설명</th></tr></thead><tbody>' + rows + '</tbody></table>' : '<p class="text-muted">로드된 도구가 없습니다.</p>') +
                '</div>' + mpHtml;
            setLoading(false);
        } catch (e) {
            setLoading(false);
            showToast('도구 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">도구 목록을 불러올 수 없습니다.</p>';
        }
    }

    window._mpAction = async function (action, name) {
        if (!confirm(action === 'install' ? name + ' 도구를 설치하시겠습니까?' : name + ' 도구를 제거하시겠습니까?')) return;
        try {
            await api('/tools/marketplace/' + action, { method: 'POST', body: JSON.stringify({ tool_name: name }) });
            showToast(name + (action === 'install' ? ' 설치 완료' : ' 제거 완료'), 'success');
            renderTools();
        } catch (e) {
            showToast('작업 실패: ' + e.message, 'error');
        }
    };

    // ---- 메모리 페이지 ----
    async function renderMemory() {
        setLoading(true);
        try {
            var data = await api('/memory');
            var rows = (data.memories || []).map(function (m) {
                var id = m.id || m.key || '';
                return '<tr><td>' + esc(m.category || '') + '</td><td>' + esc(m.key || '') + '</td><td>' + esc(truncate(m.value || '', 80)) + '</td><td>' + (m.importance || '') + '</td>' +
                    '<td><button class="btn-danger" onclick="window._memDel(\'' + esc(id) + '\')">삭제</button></td></tr>';
            }).join('');
            document.getElementById('page-content').innerHTML =
                '<div class="card"><div class="card-title">메모리 추가</div>' +
                    '<div class="form-row">' +
                        '<div class="form-group"><label>카테고리</label><select id="mem-cat"><option value="preference">preference</option><option value="fact">fact</option><option value="instruction">instruction</option><option value="context">context</option><option value="skill">skill</option></select></div>' +
                        '<div class="form-group"><label>키</label><input type="text" id="mem-key" placeholder="키 입력"></div>' +
                        '<div class="form-group"><label>값</label><input type="text" id="mem-val" placeholder="값 입력"></div>' +
                        '<div class="form-group"><label>중요도 (<span id="imp-display">3</span>)</label><input type="range" id="mem-imp" min="1" max="5" value="3"></div>' +
                        '<div class="form-group"><button class="btn-primary" onclick="window._memAdd()">추가</button></div>' +
                    '</div>' +
                '</div>' +
                '<div class="card"><div class="card-title">메모리 목록 (' + (data.count || 0) + '개)</div>' +
                (rows ? '<table><thead><tr><th>카테고리</th><th>키</th><th>값</th><th>중요도</th><th>작업</th></tr></thead><tbody>' + rows + '</tbody></table>' : '<p class="text-muted">저장된 메모리가 없습니다.</p>') +
                '</div>';
            // 슬라이더 표시 연동
            var slider = document.getElementById('mem-imp');
            var display = document.getElementById('imp-display');
            if (slider && display) {
                slider.addEventListener('input', function () { display.textContent = slider.value; });
            }
            setLoading(false);
        } catch (e) {
            setLoading(false);
            showToast('메모리 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">메모리를 불러올 수 없습니다.</p>';
        }
    }

    window._memAdd = async function () {
        var cat = document.getElementById('mem-cat').value;
        var key = document.getElementById('mem-key').value.trim();
        var val = document.getElementById('mem-val').value.trim();
        var imp = parseInt(document.getElementById('mem-imp').value, 10);
        if (!key) { showToast('키를 입력하세요.', 'warning'); return; }
        try {
            await api('/memory', { method: 'POST', body: JSON.stringify({ category: cat, key: key, value: val, importance: imp }) });
            showToast('메모리가 추가되었습니다.', 'success');
            renderMemory();
        } catch (e) { showToast('메모리 추가 실패: ' + e.message, 'error'); }
    };

    window._memDel = async function (id) {
        if (!confirm('이 메모리를 삭제하시겠습니까?')) return;
        try {
            await api('/memory/' + id, { method: 'DELETE' });
            showToast('메모리가 삭제되었습니다.', 'success');
            renderMemory();
        } catch (e) { showToast('메모리 삭제 실패: ' + e.message, 'error'); }
    };

    // ---- 스케줄 페이지 ----
    async function renderSchedules() {
        setLoading(true);
        try {
            var data = await api('/schedules');
            var rows = (data.schedules || []).map(function (s) {
                var id = s.id || '';
                return '<tr><td>' + esc(s.description || s.name || '') + '</td><td><code>' + esc(s.cron || s.schedule || '') + '</code></td><td>' + esc(s.type || '') + '</td>' +
                    '<td><button class="btn-danger" onclick="window._schDel(\'' + esc(id) + '\')">삭제</button></td></tr>';
            }).join('');
            document.getElementById('page-content').innerHTML =
                '<div class="card"><div class="card-title">스케줄 추가</div>' +
                    '<div class="form-row">' +
                        '<div class="form-group"><label>이름</label><input type="text" id="sch-name" placeholder="작업 이름"></div>' +
                        '<div class="form-group"><label>Cron 표현식</label><input type="text" id="sch-cron" placeholder="*/30 * * * *"></div>' +
                        '<div class="form-group"><label>액션</label><input type="text" id="sch-action" placeholder="remind" value="remind"></div>' +
                        '<div class="form-group"><button class="btn-primary" onclick="window._schAdd()">추가</button></div>' +
                    '</div>' +
                '</div>' +
                '<div class="card"><div class="card-title">스케줄 목록 (' + (data.count || 0) + '개)</div>' +
                (rows ? '<table><thead><tr><th>이름</th><th>Cron</th><th>유형</th><th>작업</th></tr></thead><tbody>' + rows + '</tbody></table>' : '<p class="text-muted">등록된 스케줄이 없습니다.</p>') +
                '</div>';
            setLoading(false);
        } catch (e) {
            setLoading(false);
            showToast('스케줄 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">스케줄을 불러올 수 없습니다.</p>';
        }
    }

    window._schAdd = async function () {
        var name = document.getElementById('sch-name').value.trim();
        var cron = document.getElementById('sch-cron').value.trim();
        var action = document.getElementById('sch-action').value.trim() || 'remind';
        if (!name || !cron) { showToast('이름과 Cron 표현식을 입력하세요.', 'warning'); return; }
        try {
            await api('/schedules', { method: 'POST', body: JSON.stringify({ name: name, cron: cron, action: action }) });
            showToast('스케줄이 추가되었습니다.', 'success');
            renderSchedules();
        } catch (e) { showToast('스케줄 추가 실패: ' + e.message, 'error'); }
    };

    window._schDel = async function (id) {
        if (!confirm('이 스케줄을 삭제하시겠습니까?')) return;
        try {
            await api('/schedules/' + id, { method: 'DELETE' });
            showToast('스케줄이 삭제되었습니다.', 'success');
            renderSchedules();
        } catch (e) { showToast('스케줄 삭제 실패: ' + e.message, 'error'); }
    };

    // ---- 지식 페이지 ----
    async function renderKnowledge() {
        setLoading(true);
        try {
            var data = await api('/knowledge');
            var stats = data.stats || {};
            var docsRows = (data.documents || []).map(function (d) {
                return '<tr><td>' + esc(d.title || d.id || '') + '</td><td>' + esc(truncate(d.content || d.summary || '', 100)) + '</td></tr>';
            }).join('');
            var availBadge = data.available
                ? '<span class="status-dot green"></span>활성'
                : '<span class="status-dot red"></span>비활성';
            document.getElementById('page-content').innerHTML =
                '<div class="grid-2">' +
                    '<div class="card"><div class="stat-value">' + (stats.total_documents || 0) + '</div><div class="stat-label">총 문서 수</div></div>' +
                    '<div class="card"><div class="stat-value" style="font-size:1rem">' + availBadge + '</div><div class="stat-label">서비스 상태</div></div>' +
                '</div>' +
                '<div class="card"><div class="card-title">검색</div>' +
                    '<div class="form-row"><div class="form-group" style="flex:3"><input type="text" id="kb-query" placeholder="검색어 입력" style="width:100%"></div>' +
                    '<div class="form-group"><button class="btn-primary" onclick="window._kbSearch()">검색</button></div></div>' +
                    '<div id="kb-results"></div></div>' +
                '<div class="card"><div class="card-title">문서 추가</div>' +
                    '<div class="form-group"><label>제목</label><input type="text" id="kb-title" placeholder="문서 제목" style="width:100%"></div>' +
                    '<div class="form-group"><label>내용</label><textarea id="kb-content" placeholder="문서 내용" style="width:100%"></textarea></div>' +
                    '<button class="btn-primary" onclick="window._kbAdd()">추가</button></div>' +
                (docsRows ? '<div class="card"><div class="card-title">문서 목록</div><table><thead><tr><th>제목</th><th>내용</th></tr></thead><tbody>' + docsRows + '</tbody></table></div>' : '');
            setLoading(false);
        } catch (e) {
            setLoading(false);
            showToast('지식 베이스 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">지식 베이스를 불러올 수 없습니다.</p>';
        }
    }

    window._kbSearch = async function () {
        var query = document.getElementById('kb-query').value.trim();
        if (!query) { showToast('검색어를 입력하세요.', 'warning'); return; }
        var resultsEl = document.getElementById('kb-results');
        resultsEl.innerHTML = '<p class="text-muted">검색 중...</p>';
        try {
            var data = await api('/knowledge/search', { method: 'POST', body: JSON.stringify({ query: query }) });
            var results = data.results || [];
            if (results.length === 0) {
                resultsEl.innerHTML = '<p class="text-muted mt-1">결과가 없습니다.</p>';
            } else {
                resultsEl.innerHTML = '<table class="mt-1"><thead><tr><th>제목</th><th>관련도</th><th>내용</th></tr></thead><tbody>' +
                    results.map(function (r) {
                        return '<tr><td>' + esc(r.title || '') + '</td><td>' + (r.score != null ? r.score.toFixed(2) : '-') + '</td><td>' + esc(truncate(r.content || r.snippet || '', 120)) + '</td></tr>';
                    }).join('') + '</tbody></table>';
            }
        } catch (e) {
            resultsEl.innerHTML = '<p class="text-error">검색 실패: ' + esc(e.message) + '</p>';
        }
    };

    window._kbAdd = async function () {
        var title = document.getElementById('kb-title').value.trim();
        var content = document.getElementById('kb-content').value.trim();
        if (!title || !content) { showToast('제목과 내용을 입력하세요.', 'warning'); return; }
        try {
            await api('/knowledge/index', { method: 'POST', body: JSON.stringify({ title: title, content: content }) });
            showToast('문서가 추가되었습니다.', 'success');
            renderKnowledge();
        } catch (e) { showToast('문서 추가 실패: ' + e.message, 'error'); }
    };

    // ---- 사용량 페이지 ----
    async function renderUsage() {
        setLoading(true);
        try {
            var data = await api('/usage');
            var calls = data.calls || 0;
            var inputTok = data.input_tokens || 0;
            var outputTok = data.output_tokens || 0;
            var maxVal = Math.max(calls, inputTok, outputTok, 1);
            function barPct(v) { return Math.max((v / maxVal) * 100, 0.5); }
            document.getElementById('page-content').innerHTML =
                '<div class="grid-3">' +
                    '<div class="card"><div class="stat-value">' + calls.toLocaleString() + '</div><div class="stat-label">일일 API 호출</div></div>' +
                    '<div class="card"><div class="stat-value">' + inputTok.toLocaleString() + '</div><div class="stat-label">입력 토큰</div></div>' +
                    '<div class="card"><div class="stat-value">' + outputTok.toLocaleString() + '</div><div class="stat-label">출력 토큰</div></div>' +
                '</div>' +
                '<div class="card mt-1"><div class="card-title">사용량 시각화</div>' +
                    '<div class="bar-row"><div class="bar-label">API 호출</div><div class="bar-track"><div class="bar-fill" style="width:' + barPct(calls) + '%;background:var(--accent)"></div></div><div class="bar-value">' + calls.toLocaleString() + '</div></div>' +
                    '<div class="bar-row"><div class="bar-label">입력 토큰</div><div class="bar-track"><div class="bar-fill" style="width:' + barPct(inputTok) + '%;background:var(--success)"></div></div><div class="bar-value">' + inputTok.toLocaleString() + '</div></div>' +
                    '<div class="bar-row"><div class="bar-label">출력 토큰</div><div class="bar-track"><div class="bar-fill" style="width:' + barPct(outputTok) + '%;background:var(--warning)"></div></div><div class="bar-value">' + outputTok.toLocaleString() + '</div></div>' +
                '</div>' +
                '<p class="text-muted mt-1">날짜: ' + esc(data.date || new Date().toISOString().slice(0, 10)) + '</p>';
            setLoading(false);
        } catch (e) {
            setLoading(false);
            showToast('사용량 조회 실패: ' + e.message, 'error');
            document.getElementById('page-content').innerHTML = '<p class="text-error">사용량을 불러올 수 없습니다.</p>';
        }
    }

    // ---- 유틸리티 ----
    function esc(str) {
        var d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function truncate(str, len) {
        return str.length > len ? str.slice(0, len) + '...' : str;
    }

    // ---- 초기화 ----
    navigateTo(currentSection());
})();
