document.addEventListener('DOMContentLoaded', () => {
    const isLocalHost = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    const API_BASE_URL = isLocalHost
        ? 'http://localhost:8000'
        : 'https://llm-graph-framework.onrender.com';
    const PROMPT_KEY = 'expand-node';

    const overlay = document.getElementById('loading-overlay');
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
    const serviceStatusBanner = document.getElementById('service-status');
    let backendOnline = true;

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

    cytoscape.use(cytoscapeDagre);

    const cy = cytoscape({
        container: document.getElementById('cy'),
        wheelSensitivity: 0.25,
        minZoom: 0.25,
        maxZoom: 2.5,
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
            applyTreeLayout({ fit: false });
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
            applyTreeLayout({ fit: false });
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
            applyTreeLayout({ fit: false });
            selectNodeById(newNode.id);
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
            // This is inefficient (O(N) requests). A production system should
            // use a single API endpoint for batch deletion, e.g., DELETE /graph.
            const nodeIds = cy.nodes().map((node) => node.id());
            for (const nodeId of nodeIds) {
                await request(`/nodes/${nodeId}`, { method: 'DELETE' });
            }
            cy.elements().remove();
            clearSelection();
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
            applyTreeLayout({ fit: true });

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

    function applyTreeLayout({ fit = false } = {}) {
        if (!cy.nodes().length) {
            return;
        }

        const rootsCollection = cy.nodes().roots();
        const rootIds = rootsCollection.length ? rootsCollection.map((node) => node.id()) : undefined;

        const layout = cy.layout({
            name: 'dagre',
            fit,
            animate: true,
            animationDuration: 450,
            nodeDimensionsIncludeLabels: true,
            rankDir: 'TB',
            rankSep: 140,
            nodeSep: 50,
            edgeSep: 50,
            padding: 120,
            spacingFactor: 1.1,
            roots: rootIds
        });

        layout.run();
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
        updatePromptActions({ silent: true });
    }

    function updatePromptActions(options = {}) {
        const isDirty = promptTextarea.value !== promptSnapshot;

        savePromptButton.disabled = !isDirty;
        resetPromptButton.disabled = !isDirty;
    }

    function setServiceStatus(isOnline, message = 'Backend is waking up…') {
        if (!serviceStatusBanner) {
            return;
        }
        if (isOnline) {
            if (backendOnline) {
                return;
            }
            backendOnline = true;
            serviceStatusBanner.classList.add('hidden');
            serviceStatusBanner.textContent = '';
        } else {
            backendOnline = false;
            serviceStatusBanner.textContent = message;
            serviceStatusBanner.classList.remove('hidden');
        }
    }

    async function request(path, options = {}) {
        const config = {
            method: options.method || 'GET',
            headers: options.headers ? { ...options.headers } : {}
        };

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
            setServiceStatus(false, 'Backend is waking up… please retry in a few seconds.');
            throw error;
        }

        if (!response.ok) {
            if (response.status >= 500) {
                setServiceStatus(false, 'Backend issue detected… attempting to recover.');
            }
            const message = await response.text();
            throw new Error(message || `Request failed with status ${response.status}`);
        }
        setServiceStatus(true);

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
            alert(error.message || 'Something went wrong. Check the console for details.');
        } finally {
            hideLoading();
        }
    }

    function showLoading(message = 'Working…') {
        overlayMessage.textContent = message;
        overlay.classList.remove('hidden');
    }

    function hideLoading() {
        overlay.classList.add('hidden');
        overlayMessage.textContent = 'Working…';
    }
});
