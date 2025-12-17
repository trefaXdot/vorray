document.addEventListener('DOMContentLoaded', () => {
    // === UI Элементы ===
    const step1Urls = document.getElementById('step1-urls');
    const step2Filters = document.getElementById('step2-filters');
    const modalUrls = document.getElementById('modal-urls');
    const modalStats = document.getElementById('modal-stats'); // Новый модал
    const modalProcessing = document.getElementById('modal-processing');
    const modalSuccess = document.getElementById('modal-success');
    
    const manageUrlsBtn = document.getElementById('manage-urls-btn');
    const processBtn = document.getElementById('process-btn');
    const saveUrlsBtn = document.getElementById('save-urls-btn');
    const cancelUrlsBtn = document.getElementById('cancel-urls-btn');
    const filterBtn = document.getElementById('filter-btn');
    const downloadBtn = document.getElementById('download-btn');
    const restartBtn = document.getElementById('restart-btn');
    const copyBtn = document.getElementById('copy-btn'); // Новая кнопка
    const showStatsBtn = document.getElementById('show-stats-btn'); // Новая кнопка
    const closeStatsBtn = document.getElementById('close-stats-btn'); // Кнопка закрытия статы
    const dedupeCheckbox = document.getElementById('dedupe-checkbox'); // Чекбокс

    const urlsList = document.getElementById('urls-list');
    const filterSubtitle = document.getElementById('filter-subtitle');
    const modalTitleProcessing = document.getElementById('modal-title-processing');
    const modalStatus = document.getElementById('modal-status');
    const successMessage = document.getElementById('success-message');
    const statsTableBody = document.querySelector('#stats-table tbody'); // Тело таблицы
    
    let currentSessionId = null;
    let lastStats = []; // Хранение статистики

    // === Вспомогательные функции ===
    function showToast(message, isError = false) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${isError ? 'error' : 'success'}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    }
    
    function showScreen(screen) {
        [step1Urls, step2Filters].forEach(s => s.classList.add('hidden'));
        if (screen) screen.classList.remove('hidden');
    }

    function showProcessingModal(title, status) {
        modalTitleProcessing.textContent = title;
        modalStatus.textContent = status;
        modalProcessing.classList.remove('hidden');
    }
    
    async function checkUrlListStatus() {
        try {
            const response = await fetch('/api/urls');
            if (!response.ok) { processBtn.disabled = true; return; }
            const data = await response.json();
            const urlsExist = data.urls && data.urls.trim() !== '';
            processBtn.disabled = !urlsExist;
        } catch (error) {
            processBtn.disabled = true;
            showToast('Не удалось проверить список URL.', true);
        }
    }

    function shortenUrl(urlString) {
        const trimmedUrl = urlString.trim();
        if (!trimmedUrl) return '';
        try {
            const url = new URL(trimmedUrl);
            const pathParts = url.pathname.split('/').filter(p => p);
            if (pathParts.length < 2) return trimmedUrl;
            const user = pathParts[0];
            let fileName = pathParts[pathParts.length - 1];
            fileName = fileName.replace(/\.txt$/, '').replace(/\.sub$/, '');
            return `${user} - ${fileName}`;
        } catch (e) {
            return trimmedUrl;
        }
    }
    
    function cleanupEmptyListItems() {
        const allItems = urlsList.querySelectorAll('li');
        const emptyItems = Array.from(allItems).filter(li => li.dataset.fullUrl.trim() === '');
        if (emptyItems.length > 1) {
            for (let i = 0; i < emptyItems.length - 1; i++) {
                emptyItems[i].remove();
            }
        }
    }

    function createUrlListItem(fullUrl = '') {
        const li = document.createElement('li');
        const urlContent = document.createElement('div');
        const deleteBtn = document.createElement('button');

        li.dataset.fullUrl = fullUrl.trim();
        
        urlContent.className = 'url-content';
        urlContent.textContent = shortenUrl(fullUrl);
        urlContent.setAttribute('contenteditable', 'true');
        urlContent.setAttribute('spellcheck', 'false');

        deleteBtn.className = 'delete-btn';
        deleteBtn.innerHTML = '&times;';
        deleteBtn.setAttribute('title', 'Удалить');
        deleteBtn.setAttribute('contenteditable', 'false'); 

        li.appendChild(urlContent);
        li.appendChild(deleteBtn);

        if (!fullUrl.trim()) {
            li.classList.add('list-item--empty');
        }

        deleteBtn.addEventListener('click', () => {
            li.remove();
            const allItems = urlsList.querySelectorAll('li');
            const emptyItems = Array.from(allItems).filter(item => item.dataset.fullUrl.trim() === '');
            if (emptyItems.length === 0) {
                urlsList.appendChild(createUrlListItem(''));
            }
        });

        return li;
    }

    // === Функции Статистики ===
    function renderStatsTable(stats) {
        statsTableBody.innerHTML = '';
        stats.forEach(item => {
            const tr = document.createElement('tr');
            
            const tdUrl = document.createElement('td');
            tdUrl.className = 'url-cell';
            tdUrl.title = item.url;
            tdUrl.textContent = shortenUrl(item.url); // Показываем сокращенный, полный в title
            
            const tdStatus = document.createElement('td');
            if (item.status === 'ok') {
                tdStatus.innerHTML = '<span class="status-ok">OK</span>';
            } else {
                tdStatus.innerHTML = `<span class="status-error" title="${item.msg}">ERR</span>`;
            }
            
            const tdCount = document.createElement('td');
            tdCount.textContent = item.count;
            
            tr.appendChild(tdUrl);
            tr.appendChild(tdStatus);
            tr.appendChild(tdCount);
            statsTableBody.appendChild(tr);
        });
    }

    // === Основные функции ===

    async function handleManageUrls() {
        try {
            const response = await fetch('/api/urls');
            if (!response.ok) throw new Error('Ошибка загрузки URL');
            const data = await response.json();
            
            urlsList.innerHTML = '';
            
            const urls = data.urls ? data.urls.split('\n').filter(url => url.trim() !== '') : [];
            urls.forEach(url => urlsList.appendChild(createUrlListItem(url)));
            urlsList.appendChild(createUrlListItem(''));
            
            modalUrls.classList.remove('hidden');
        } catch (error) {
            showToast(error.message, true);
        }
    }

    async function handleSaveUrls() {
        try {
            cleanupEmptyListItems();
            const urlItems = urlsList.querySelectorAll('li');
            const urlsToSave = Array.from(urlItems)
                .map(li => li.dataset.fullUrl.trim())
                .filter(url => url !== '');

            const response = await fetch('/api/save_urls', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls: urlsToSave.join('\n') }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.message || 'Ошибка сохранения');
            
            showToast(result.message, false);
            modalUrls.classList.add('hidden');
            await checkUrlListStatus();
        } catch (error) {
            showToast(error.message, true);
        }
    }

    async function handleStep1() {
        showProcessingModal('Шаг 1: Обработка', 'Скачиваем источники...');
        
        // Читаем состояние чекбокса
        const isDedupe = dedupeCheckbox.checked;

        try {
            const response = await fetch('/api/step1_process', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deduplicate: isDedupe })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Ошибка на сервере');
            
            currentSessionId = result.sessionId;
            lastStats = result.stats; // Сохраняем стату
            
            filterSubtitle.textContent = `Собрано ${result.uniqueCount} конфигов (всего найдено: ${result.totalFound}).`;
            modalProcessing.classList.add('hidden');
            showScreen(step2Filters);

            showToast(`Обработано. Доступно: ${result.uniqueCount}`);
        } catch (error) {
            modalProcessing.classList.add('hidden');
            showToast(error.message, true);
        }
    }

    async function handleStep2() {
        showProcessingModal('Шаг 2: Фильтрация', 'Удаляем конфиги по вашим правилам...');
        const selectedFilters = [...document.querySelectorAll('input[name="filters"]:checked')].map(el => el.value);
        try {
            const response = await fetch('/api/step2_filter', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sessionId: currentSessionId, filters: selectedFilters }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Ошибка на сервере');
            
            successMessage.textContent = `Готово ${result.finalCount} конфигов.`;
            modalProcessing.classList.add('hidden');
            modalSuccess.classList.remove('hidden');

            const filteredRemoved = result.initialCount - result.finalCount;
            showToast(`Фильтрация завершена.\nУдалено: ${filteredRemoved}.`);
        } catch (error) {
            modalProcessing.classList.add('hidden');
            showToast(error.message, true);
        }
    }

    function handleDownload() {
        if (!currentSessionId) return;
        window.location.href = `/api/step3_download/${currentSessionId}`;
    }

    // Новая функция: Копирование
    async function handleCopy() {
        if (!currentSessionId) return;
        try {
            const response = await fetch(`/api/get_content/${currentSessionId}`);
            if (!response.ok) throw new Error('Ошибка получения данных');
            const text = await response.text();
            
            await navigator.clipboard.writeText(text);
            showToast("Конфиги скопированы в буфер обмена!");
        } catch (error) {
            showToast("Не удалось скопировать: " + error.message, true);
        }
    }

    function resetApp() {
        modalSuccess.classList.add('hidden');
        showScreen(step1Urls);
        currentSessionId = null;
        lastStats = [];
        document.querySelectorAll('input[name="filters"]:checked').forEach(el => el.checked = false);
        checkUrlListStatus();
    }
    
    function setupUrlListEventListeners() {
        urlsList.addEventListener('input', (e) => {
            const li = e.target.closest('li');
            if (li && li === urlsList.lastElementChild) {
                urlsList.appendChild(createUrlListItem(''));
            }
        });

        urlsList.addEventListener('focusin', (e) => {
            const contentDiv = e.target.closest('.url-content');
            if (contentDiv) {
                contentDiv.textContent = contentDiv.parentElement.dataset.fullUrl;
            }
        });

        urlsList.addEventListener('focusout', (e) => {
            const contentDiv = e.target.closest('.url-content');
            if (contentDiv) {
                const li = contentDiv.parentElement;
                const newFullUrl = contentDiv.textContent.trim();
                li.dataset.fullUrl = newFullUrl;
                contentDiv.textContent = shortenUrl(newFullUrl);
                
                if (newFullUrl) {
                    li.classList.remove('list-item--empty');
                } else {
                    li.classList.add('list-item--empty');
                }
                
                cleanupEmptyListItems();
            }
        });

        urlsList.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData('text/plain');
            const lines = text.split('\n').map(line => line.trim()).filter(line => line);
            if (lines.length === 0) return;
            
            const contentDiv = e.target.closest('.url-content');
            const li = contentDiv.parentElement;
            
            li.dataset.fullUrl = lines[0];
            contentDiv.textContent = lines[0];
            li.classList.remove('list-item--empty');

            let lastPastedLi = li;
            for (let i = 1; i < lines.length; i++) {
                const newLi = createUrlListItem(lines[i]);
                lastPastedLi.insertAdjacentElement('afterend', newLi);
                lastPastedLi = newLi;
            }
        });
    }

    // === Инициализация и обработчики событий ===
    manageUrlsBtn.addEventListener('click', handleManageUrls);
    saveUrlsBtn.addEventListener('click', handleSaveUrls);
    cancelUrlsBtn.addEventListener('click', () => modalUrls.classList.add('hidden'));
    
    processBtn.addEventListener('click', handleStep1);
    
    showStatsBtn.addEventListener('click', () => {
        renderStatsTable(lastStats);
        modalStats.classList.remove('hidden');
    });
    closeStatsBtn.addEventListener('click', () => modalStats.classList.add('hidden'));

    filterBtn.addEventListener('click', handleStep2);
    
    downloadBtn.addEventListener('click', handleDownload);
    copyBtn.addEventListener('click', handleCopy); // Биндинг копирования
    restartBtn.addEventListener('click', resetApp);

    setupUrlListEventListeners();
    checkUrlListStatus();
});