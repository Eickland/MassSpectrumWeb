// API URL
const API_BASE = '/api';

// Закрытие по кнопке Esc
document.addEventListener('keydown', (e) => {
    if (e.key === "Escape") closeModal();
});
// Load projects on page load
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    loadSamples();

    // Import button handler
    const importBtn = document.getElementById('importBtn');
    if (importBtn) {
        importBtn.addEventListener('click', importData);
    }

    // Search input handler
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', filterSamples);
    }

    // Project filter handler
    const projectFilter = document.getElementById('projectFilter');
    if (projectFilter) {
        projectFilter.addEventListener('change', filterSamples);
    }
});

// Load projects
async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/projects`);
        const projects = await response.json();
        
        const projectsList = document.getElementById('projects-list');
        const projectFilter = document.getElementById('projectFilter');
        
        if (projectsList) {
            projectsList.innerHTML = '';
            
            // Кнопка "Все проекты"
            const allEl = document.createElement('div');
            allEl.className = 'project-item active';
            allEl.textContent = 'All Projects';
            allEl.addEventListener('click', () => {
                document.querySelectorAll('.sample-card').forEach(c => c.style.display = 'flex');
                document.querySelectorAll('.project-item').forEach(i => i.classList.remove('active'));
                allEl.classList.add('active');
            });
            projectsList.appendChild(allEl);
            projects.forEach(project => {
                const projectEl = document.createElement('div');
                projectEl.className = 'project-item';
                projectEl.textContent = project.name;
                projectEl.dataset.project = project.name;
                projectEl.addEventListener('click', () => filterByProject(project.name));
                projectsList.appendChild(projectEl);
            });
        }

        if (projectFilter) {
            projectFilter.innerHTML = '<option value="all">All Projects</option>';
            projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.name;
                option.textContent = project.name;
                projectFilter.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading projects:', error);
    }
}

// Load samples
async function loadSamples() {
    try {
        const response = await fetch(`${API_BASE}/samples`);
        const samples = await response.json();
        displaySamples(samples);
    } catch (error) {
        console.error('Error loading samples:', error);
    }
}

// Display samples in grid
function displaySamples(samples) {
    const samplesGrid = document.getElementById('samples-grid');
    const samplesList = document.getElementById('samples-list');
    
    const container = samplesGrid || samplesList;
    if (!container) return;

    container.innerHTML = '';

    samples.forEach(sample => {
        const card = createSampleCard(sample);
        container.appendChild(card);
    });
}

// Create sample card element
function createSampleCard(sample) {
    const card = document.createElement('div');
    card.className = 'sample-card';
    
    // ВАЖНО: Добавляем атрибут для фильтрации
    card.dataset.project = sample.project;
    card.dataset.name = sample.name;

    const images = sample.graphs.filter(g => ['png', 'jpg', 'jpeg'].includes(g.file_type));
    const dataFiles = sample.graphs.filter(g => ['xlsx', 'csv', 'pdf'].includes(g.file_type));
    const mainImg = images.find(g => g.is_main) || images[0];

    // JSON.stringify для модалки
    const sampleData = JSON.stringify(sample).replace(/"/g, '&quot;');

    card.innerHTML = `
        <div class="image-container">
            <img src="${mainImg ? mainImg.file_path : ''}" 
                 class="sample-image" 
                 style="cursor: pointer;"
                 onclick="openDetailedModal(${sampleData})"> 
            ${images.length > 1 ? `<span class="badge">🖼️ ${images.length}</span>` : ''}
        </div>
        <div class="sample-info">
            <div class="sample-header">
                <span class="sample-name">${sample.name}</span>
                <span class="sample-project-tag">${sample.project}</span>
            </div>
            <div class="data-files-list">
                ${dataFiles.map(file => `
                    <a href="${file.file_path}" class="file-link" download onclick="event.stopPropagation()">
                        ${file.file_type === 'xlsx' ? '📊' : '📄'} ${file.name}
                    </a>
                `).join('')}
            </div>
        </div>
    `;
    return card;
}

// Filter samples by project
function filterByProject(projectName) {
    const cards = document.querySelectorAll('.sample-card');
    const projectItems = document.querySelectorAll('.project-item');
    
    // Подсвечиваем активный проект в сайдбаре
    projectItems.forEach(item => {
        if (item.dataset.project === projectName) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Скрываем или показываем карточки
    cards.forEach(card => {
        // Если проект совпадает или мы нажали на уже активный проект (для сброса)
        if (card.dataset.project === projectName) {
            card.style.display = 'flex'; // или 'block', смотря что в CSS
        } else {
            card.style.display = 'none';
        }
    });
}

// Filter samples by search and project
function filterSamples() {
    const searchTerm = document.getElementById('searchInput')?.value.toLowerCase() || '';
    const projectFilter = document.getElementById('projectFilter')?.value || 'all';
    
    const cards = document.querySelectorAll('.sample-card');
    
    cards.forEach(card => {
        const name = card.dataset.name.toLowerCase();
        const project = card.dataset.project;
        
        const matchesSearch = name.includes(searchTerm);
        const matchesProject = projectFilter === 'all' || project === projectFilter;
        
        card.style.display = matchesSearch && matchesProject ? 'block' : 'none';
    });
}

// Import new data
async function importData() {
    try {
        const response = await fetch(`${API_BASE}/import`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const result = await response.json();
            alert(`Import successful: ${result.message}`);
            loadSamples();
        } else {
            alert('Import failed');
        }
    } catch (error) {
        console.error('Error importing data:', error);
        alert('Error importing data');
    }
}

// Show specific graph (for future multiple graphs feature)
function showGraph(sampleName, graphIndex) {
    console.log('Show graph', graphIndex, 'for sample', sampleName);
    // В будущем здесь будет логика для показа большого графика
}

function openModal(src, name) {
    const modal = document.getElementById('imageModal');
    const modalImg = document.getElementById('fullImage');
    const captionText = document.getElementById('caption');
    const downloadBtn = document.getElementById('downloadBtn');

    modal.style.display = "block";
    modalImg.src = src;
    captionText.innerHTML = name;

    // Настраиваем кнопку скачивания
    downloadBtn.href = src; // Путь к файлу (/data/...)
    downloadBtn.download = name; // Имя, под которым файл сохранится

    document.body.style.overflow = 'hidden';
}

function closeModal() {
    const modal = document.getElementById('imageModal');
    if (modal) {
        modal.style.display = "none";
    }
    document.body.style.overflow = 'auto';
}

let currentSampleData = null;

function openDetailedModal(sample) {
    currentSampleData = sample;
    const images = sample.graphs.filter(g => ['png', 'jpg', 'jpeg'].includes(g.file_type));
    
    if (images.length === 0) return;

    // Показываем первый график
    switchModalImage(images[0], 0);
    
    // Генерируем миниатюры
    const thumbContainer = document.getElementById('thumbnailsContainer');
    thumbContainer.innerHTML = '';
    
    if (images.length > 1) {
        images.forEach((img, index) => {
            const thumb = document.createElement('img');
            thumb.src = img.file_path;
            thumb.className = 'thumb-item' + (index === 0 ? ' active' : '');
            thumb.onclick = (e) => {
                e.stopPropagation();
                switchModalImage(img, index);
            };
            thumbContainer.appendChild(thumb);
        });
        thumbContainer.style.display = 'flex';
    } else {
        thumbContainer.style.display = 'none';
    }

    document.getElementById('imageModal').style.display = "block";
    document.body.style.overflow = 'hidden';
}

function switchModalImage(graph, index) {
    const modalImg = document.getElementById('fullImage');
    const captionText = document.getElementById('caption');
    const downloadBtn = document.getElementById('downloadBtn');
    
    modalImg.src = graph.file_path;
    captionText.innerHTML = `${currentSampleData.name} — ${graph.name}`;
    
    downloadBtn.href = graph.file_path;
    downloadBtn.download = `${currentSampleData.name}__${graph.name}.${graph.file_type}`;

    // Подсвечиваем активную миниатюру
    document.querySelectorAll('.thumb-item').forEach((t, i) => {
        t.classList.toggle('active', i === index);
    });
}

