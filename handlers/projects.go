package handlers

import (
    "encoding/json"
    "net/http"
    "sort"

    "github.com/gorilla/mux"
    "mass-spec-server/models"
)

type ProjectHandler struct {
    labJournal *models.LabJournal
}

func NewProjectHandler(labJournal *models.LabJournal) *ProjectHandler {
    return &ProjectHandler{
        labJournal: labJournal,
    }
}

// GetAllProjects возвращает все проекты
func (h *ProjectHandler) GetAllProjects(w http.ResponseWriter, r *http.Request) {
    projects := make([]models.ProjectInfo, 0, len(h.labJournal.Projects))
    for _, project := range h.labJournal.Projects {
        projects = append(projects, project)
    }

    // Добавляем стандартный проект для несортированных образцов
    projects = append(projects, models.ProjectInfo{
        Name:        "Uncategorized",
        Description: "Samples without project assignment",
    })

    sort.Slice(projects, func(i, j int) bool {
        return projects[i].Name < projects[j].Name
    })

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(projects)
}

// GetProjectSamples возвращает образцы проекта
func (h *ProjectHandler) GetProjectSamples(w http.ResponseWriter, r *http.Request) {
    vars := mux.Vars(r)
    projectName := vars["name"]

    // Здесь нужно будет получать актуальные образцы из SampleHandler
    // Для простоты возвращаем заглушку
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]interface{}{
        "project": projectName,
        "samples": []string{},
    })
}