document.addEventListener('DOMContentLoaded', () => {
    const isLocalHost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    const API_BASE_URL = isLocalHost
        ? 'http://localhost:8000'
        : 'https://llm-graph-framework.onrender.com';
    const PROMPT_KEY = 'expand-node';
    const BACKEND_ESTIMATED_SPINUP_SECONDS = 50;
    const BACKEND_STATUS_POLL_INTERVAL = 10000;

    function generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    function getOrSetUserId() {
        const USER_ID_KEY = 'genai-graph-user-id';
        let userId = localStorage.getItem(USER_ID_KEY);
        if (!userId) {
            userId = generateUUID();
            localStorage.setItem(USER_ID_KEY, userId);
        }
        return userId;
    }
    const USER_ID = getOrSetUserId();

    const overlay = document.getElementById('loading-overlay');
    const emptyWorkspaceOverlay = document.getElementById('empty-workspace-overlay');
    const overlayMessage = overlay.querySelector('p');
    const detailsPlaceholder = document.querySelector('.details-placeholder');
    const detailsList = document.querySelector('.node-details');
    const detailName = document.getElementById('detail-name');
    const detailDescription = document.getElementById('detail-description');
    const expandButton = document.getElementById('expand-node-btn');
    const deleteButton = document.getElementById('delete-node-btn');
    const addNodeForm = document.getElementById('add-node-form');
    const clearGraphButton = document.getElementById('clear-graph-btn');
    const promptTextarea = document.getElementById('prompt-text');
    const savePromptButton = document.getElementById('save-prompt-btn');
    const resetPromptButton = document.getElementById('reset-prompt-btn');
    const tabButtons = Array.from(document.querySelectorAll('.tab-btn'));
    const tabPanes = {
        details: document.getElementById('details-tab'),
        prompt: document.getElementById('prompt-tab')
    };
    const overlayState = {
        taskDepth: 0,
        taskMessage: 'Working…',
        backend: { active: false, message: '' },
        transient: { active: false, message: '', timeoutId: null }
    };

    const backendWaitState = {
        active: false,
        timerId: null,
        startTime: null,
        baseMessage: 'Spinning up backend…'
    };

    let backendHealthCheckIntervalId = null;

    const textMetrics = (() => {
        const context = document.createElement('canvas').getContext('2d');
        return {
            measure: (text, font) => {
                context.font = font;
                return context.measureText(text).width;
            }
        };
    })();

    function truncateTextToFit(text, maxWidth, font) {
        if (textMetrics.measure(text, font) <= maxWidth) {
            return text;
        }

        let truncated = text;
        while (truncated.length > 0 && textMetrics.measure(`${truncated}…`, font) > maxWidth) {
            truncated = truncated.slice(0, -1);
        }
        return `${truncated}…`;
    }

    const state = {
        selectedNodeId: null
    };

    let promptSnapshot = '';

    // --- CORRECTED: Use the correct variable name for the Cola extension ---
    cytoscape.use(cytoscapeCola);

    const cy = cytoscape({
        container: document.getElementById('cy'),
        wheelSensitivity: 0.25,
        minZoom: 0.125,
        maxZoom: 5,
        layout: { name: 'preset' },
        style: [
            {
                selector: 'node',
                style: {
                    'background-color': '#4b63ff',
                    'border-color': '#f0f2ff',
                    'border-width': 3,
                    'shape': 'ellipse',
                    'width': 120,
                    'height': 120,
                    'label': 'data(displayName)',
                    'font-size': 'data(fontSize)',
                    'font-weight': 600,
                    'font-family': '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif',
                    'color': '#ffffff',
                    'text-halign': 'center',
                    'text-valign': 'center',
                    'text-wrap': 'wrap',
                    'text-max-width': 94,
                    'text-outline-width': 0,
                    'overlay-padding': 6,
                    'overlay-opacity': 0,
                    'transition-property': 'background-color border-color',
                    'transition-duration': 200
                }
            },
            {
                selector: 'node:selected',
                style: {
                    'background-color': '#4b63ff',
                    'text-outline-color': '#3a4acf',
                    'border-color': '#f97316',
                    'border-width': 4
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 2.5,
                    'line-color': '#d8dae6',
                    'target-arrow-color': '#d8dae6',
                    'target-arrow-shape': 'triangle',
                    'arrow-scale': 1.2,
                    'curve-style': 'bezier',
                    'opacity': 0.9,
                    'label': 'data(label)',
                    'font-size': 12,
                    'font-weight': 600,
                    'color': '#84858c',
                    'text-background-color': '#fff',
                    'text-background-opacity': 1,
                    'text-background-padding': 3,
                    'text-valign': 'top',
                    'text-rotation': 'autorotate'
                }
            },
            {
                selector: 'edge:selected',
                style: {
                    'line-color': '#f97316',
                    'target-arrow-color': '#f97316',
                    'width': 3.5
                }
            }
        ]
    });

    tabButtons.forEach((button) => {
        button.addEventListener('click', () => {
            switchTab(button.dataset.tab);
        });
    });

    expandButton.addEventListener('click', async () => {
        if (!state.selectedNodeId) {
            return;
        }
        await runTask('Expanding node…', async () => {
            const graph = await request(`/nodes/${state.selectedNodeId}/expand`, { method: 'POST' });
            mergeGraph(graph);
            applyLayout({ fit: false });
        });
    });

    deleteButton.addEventListener('click', async () => {
        if (!state.selectedNodeId) {
            return;
        }
        const nodeId = state.selectedNodeId;
        await runTask('Deleting node…', async () => {
            await request(`/nodes/${nodeId}`, { method: 'DELETE' });
            cy.remove(`#${nodeId}`);
            clearSelection();
            applyLayout({ fit: false });
            updateEmptyStateMessage();
        });
    });

    promptTextarea.addEventListener('input', () => {
        updatePromptActions();
    });

    savePromptButton.addEventListener('click', async () => {
        const promptBody = promptTextarea.value;
        await runTask('Saving prompt…', async () => {
            const payload = { prompt: promptBody };
            const response = await request(`/prompts/${PROMPT_KEY}`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            });
            applyPrompt(response.prompt);
        });
    });

    resetPromptButton.addEventListener('click', () => {
        promptTextarea.value = promptSnapshot;
        updatePromptActions();
    });

    addNodeForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = new FormData(addNodeForm);
        const name = (formData.get('name') || '').toString().trim();
        const description = (formData.get('description') || '').toString().trim();

        if (!name || !description) {
            alert('Please provide both a name and a description for the node.');
            return;
        }

        await runTask('Creating node…', async () => {
            const newNode = await request('/nodes', {
                method: 'POST',
                body: JSON.stringify({ name, description })
            });
            mergeGraph({ nodes: [newNode], edges: [] });
            addNodeForm.reset();
            applyLayout({ fit: false });
            selectNodeById(newNode.id);
            updateEmptyStateMessage();
        });
    });

    clearGraphButton.addEventListener('click', async () => {
        if (!cy.nodes().length) {
            return;
        }
        const confirmed = window.confirm('Delete all nodes from the database? This cannot be undone.');
        if (!confirmed) {
            return;
        }

        await runTask('Clearing graph…', async () => {
            const nodeIds = cy.nodes().map((node) => node.id());
            for (const nodeId of nodeIds) {
                await request(`/nodes/${nodeId}`, { method: 'DELETE' });
            }
            cy.elements().remove();
            clearSelection();
            updateEmptyStateMessage();
        });
    });

    cy.on('tap', 'node', (event) => {
        selectNode(event.target);
    });

    cy.on('tap', (event) => {
        if (event.target === cy) {
            clearSelection();
        }
    });

    cy.on('mouseover', 'node', () => document.getElementById('cy').style.cursor = 'pointer');
    cy.on('mouseout', 'node', () => document.getElementById('cy').style.cursor = 'default');
    cy.on('mouseover', 'edge', () => document.getElementById('cy').style.cursor = 'pointer');
    cy.on('mouseout', 'edge', () => document.getElementById('cy').style.cursor = 'default');

    bootstrapWorkspace();

    async function bootstrapWorkspace() {
        await runTask('Loading workspace…', async () => {
            const [graph, promptDoc] = await Promise.all([
                request('/graph'),
                request(`/prompts/${PROMPT_KEY}`)
            ]);

            cy.elements().remove();
            mergeGraph(graph);
            applyLayout({ fit: true });
            updateEmptyStateMessage();

            applyPrompt(promptDoc?.prompt || '');
        });
    }

    function mergeGraph(graphData) {
        if (!graphData) {
            return;
        }

        const elementsToAdd = [];

        (graphData.nodes || []).forEach((node) => {
            const visuals = computeNodeVisuals(node.name);
            const data = {
                id: node.id,
                name: node.name,
                description: node.description,
                displayName: visuals.displayName,
                fontSize: visuals.fontSize
            };

            const existingNode = cy.getElementById(node.id);
            if (existingNode && existingNode.length) {
                existingNode.data(data);
            } else {
                elementsToAdd.push({ data });
            }
        });

        const seenEdgeIds = new Set();
        (graphData.edges || []).forEach((edge) => {
            const edgeId = `${edge.source_id}-${edge.target_id}-${edge.label}`;
            if (seenEdgeIds.has(edgeId)) {
                return;
            }
            seenEdgeIds.add(edgeId);

            const existingEdge = cy.getElementById(edgeId);
            if (existingEdge && existingEdge.length) {
                return;

            }

            elementsToAdd.push({
                data: {
                    id: edgeId,
                    source: edge.source_id,
                    target: edge.target_id,
                    label: edge.label
                }
            });
        });

        if (elementsToAdd.length) {
            cy.add(elementsToAdd);
        }
    }

    function computeNodeVisuals(rawName) {
        const name = (rawName || 'Untitled').trim();
        const fontSize = 16;
        const font = `600 ${fontSize}px "Segoe UI"`;
        
        const maxTextWidth = 94; 

        const displayName = truncateTextToFit(name, maxTextWidth, font);

        return { displayName, fontSize };
    }

    function applyLayout({ fit = true } = {}) {
        if (!cy.nodes().length) {
            return;
        }

        const layout = cy.layout({
            name: 'cola',
            animate: true,
            animationDuration: 450,
            fit: fit,
            padding: 40,
            nodeSpacing: 50,
            edgeLength: 120,
            randomize: true,
        });

        layout.run();
    }

    function updateEmptyStateMessage() {
        const isEmpty = cy.nodes().length === 0;
        emptyWorkspaceOverlay.classList.toggle('hidden', !isEmpty);
    }

    function selectNode(element) {
        const node = coerceNode(element);
        if (!node || node.empty()) {
            return;
        }

        cy.nodes().unselect();
        node.select();
        state.selectedNodeId = node.id();
        updateDetailsPanel(node.data());
    }

    function selectNodeById(nodeId) {
        if (!nodeId) {
            return;
        }
        const nodeCollection = cy.getElementById(nodeId);
        const node = coerceNode(nodeCollection);
        if (node) {
            selectNode(node);
        }
    }

    function coerceNode(element) {
        if (!element) {
            return null;
        }
        if (typeof element.isNode === 'function' && element.isNode()) {
            return element;
        }
        if (typeof element.first === 'function') {
            const first = element.first();
            return first && typeof first.isNode === 'function' && first.isNode() ? first : null;
        }
        return null;
    }

    function clearSelection() {
        state.selectedNodeId = null;
        cy.nodes().unselect();
        updateDetailsPanel(null);
        switchTab('details');
    }

    function updateDetailsPanel(nodeData) {
        if (!nodeData) {
            detailsPlaceholder.classList.remove('hidden');
            detailsList.classList.add('hidden');
            detailName.textContent = '';
            detailDescription.textContent = '';
            setActionButtonsEnabled(false);
            return;
        }

        detailsPlaceholder.classList.add('hidden');
        detailsList.classList.remove('hidden');
        detailName.textContent = nodeData.name || 'Untitled';
        detailDescription.textContent = nodeData.description || 'No description provided.';
        setActionButtonsEnabled(true);
    }

    function setActionButtonsEnabled(isEnabled) {
        expandButton.disabled = !isEnabled;
        deleteButton.disabled = !isEnabled;
    }

    function switchTab(tabName) {
        tabButtons.forEach((button) => {
            const isActive = button.dataset.tab === tabName;
            button.classList.toggle('active', isActive);
        });

        Object.entries(tabPanes).forEach(([name, pane]) => {
            pane.classList.toggle('active', name === tabName);
        });
    }

    function applyPrompt(promptText) {
        promptSnapshot = promptText || '';
        promptTextarea.value = promptSnapshot;
        updatePromptActions();
    }

    function updatePromptActions() {
        const isDirty = promptTextarea.value !== promptSnapshot;

        savePromptButton.disabled = !isDirty;
        resetPromptButton.disabled = !isDirty;
    }

    async function evaluateHealthStatus(messagePrefix = 'Spinning up backend…') {
        const isOnline = await pingBackend();
        if (!isOnline) {
            beginBackendRecovery(messagePrefix);
        }
        return isOnline;
    }

    async function request(path, options = {}) {
        const config = {
            method: options.method || 'GET',
            headers: options.headers ? { ...options.headers } : {}
        };

        config.headers['X-User-ID'] = USER_ID;

        if (options.body) {
            config.body = options.body;
            if (!config.headers['Content-Type']) {
                config.headers['Content-Type'] = 'application/json';
            }
        }

        let response;
        try {
            response = await fetch(`${API_BASE_URL}${path}`, config);
        } catch (error) {
            beginBackendRecovery('Backend is waking up… please hold tight.');
            throw new Error('Backend is waking up… please hold tight.');
        }

        if (!response.ok) {
            if (response.status >= 500) {
                beginBackendRecovery('Backend issue detected… attempting to recover.');
            }
            const message = await response.text();
            throw new Error(message || `Request failed with status ${response.status}`);
        }
        markBackendOnline();

        if (response.status === 204) {
            return null;
        }

        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            return await response.json();
        }

        return null;
    }

    async function runTask(message, task) {
        showLoading(message);
        try {
            await task();
        } catch (error) {
            console.error(error);
            showTransientStatus(error.message || 'Something went wrong. Check the console for details.');
        } finally {
            hideLoading();
        }
    }

    evaluateHealthStatus('Connecting to backend…');

    function showLoading(message = 'Working…') {
        overlayState.taskDepth += 1;
        overlayState.taskMessage = message;
        refreshOverlay();
    }

    function hideLoading() {
        overlayState.taskDepth = Math.max(0, overlayState.taskDepth - 1);
        refreshOverlay();
    }

    function showTransientStatus(message, duration = 3000) {
        if (overlayState.transient.timeoutId) {
            clearTimeout(overlayState.transient.timeoutId);
        }
        overlayState.transient.active = true;
        overlayState.transient.message = message;
        overlayState.transient.timeoutId = setTimeout(() => {
            overlayState.transient.active = false;
            overlayState.transient.timeoutId = null;
            refreshOverlay();
        }, duration);
        refreshOverlay();
    }

    function refreshOverlay() {
        if (overlayState.taskDepth > 0) {
            overlayMessage.textContent = overlayState.taskMessage;
            overlay.classList.remove('hidden');
            return;
        }
        if (overlayState.backend.active) {
            overlayMessage.textContent = overlayState.backend.message;
            overlay.classList.remove('hidden');
            return;
        }
        if (overlayState.transient.active) {
            overlayMessage.textContent = overlayState.transient.message;
            overlay.classList.remove('hidden');
            return;
        }
        overlay.classList.add('hidden');
        overlayMessage.textContent = 'Working…';
    }

    function beginBackendRecovery(messagePrefix = 'Spinning up backend…') {
        startBackendWait(messagePrefix);
        if (backendHealthCheckIntervalId) {
            return;
        }
        backendHealthCheckIntervalId = setInterval(async () => {
            const recovered = await pingBackend();
            if (recovered) {
                clearInterval(backendHealthCheckIntervalId);
                backendHealthCheckIntervalId = null;
            }
        }, BACKEND_STATUS_POLL_INTERVAL);
    }

    function startBackendWait(messagePrefix) {
        backendWaitState.baseMessage = messagePrefix;
        if (!backendWaitState.active) {
            backendWaitState.active = true;
            backendWaitState.startTime = Date.now();
            backendWaitState.timerId = setInterval(updateBackendWaitMessage, 1000);
        }
        updateBackendWaitMessage();
    }

    function updateBackendWaitMessage() {
        if (!backendWaitState.active) {
            return;
        }
        const elapsedSeconds = Math.round((Date.now() - backendWaitState.startTime) / 1000);
        const estimate = BACKEND_ESTIMATED_SPINUP_SECONDS;
        const message = `${backendWaitState.baseMessage} ${elapsedSeconds}s / ~${estimate}s`;
        overlayState.backend.active = true;
        overlayState.backend.message = message;
        refreshOverlay();
    }

    function stopBackendWait() {
        if (!backendWaitState.active) {
            return;
        }
        backendWaitState.active = false;
        if (backendWaitState.timerId) {
            clearInterval(backendWaitState.timerId);
            backendWaitState.timerId = null;
        }
        overlayState.backend.active = false;
        overlayState.backend.message = '';
        refreshOverlay();
    }

    async function pingBackend() {
        try {
            const response = await fetch(`${API_BASE_URL}/health`, { cache: 'no-store' });
            if (response.ok) {
                markBackendOnline();
                return true;
            }
        } catch (error) {
            // swallow; handled by caller
        }
        return false;
    }

    function markBackendOnline() {
        stopBackendWait();
        if (backendHealthCheckIntervalId) {
            clearInterval(backendHealthCheckIntervalId);
            backendHealthCheckIntervalId = null;
        }
    }
});