package handlers

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"mass-spec-server/models"

	"github.com/gorilla/mux"
)

type SampleHandler struct {
	dataPath   string
	labJournal *models.LabJournal
	samples    map[string]models.Sample
}

func NewSampleHandler(dataPath string, labJournal *models.LabJournal) *SampleHandler {
	h := &SampleHandler{
		dataPath:   dataPath,
		labJournal: labJournal,
		samples:    make(map[string]models.Sample),
	}
	h.RefreshSamples()
	return h
}

func (h *SampleHandler) RefreshSamples() error {
	newSamples := make(map[string]models.Sample)

	// Путь к папке с графиками - теперь используем h.dataPath напрямую
	// вместо создания подпапки "graphs"
	graphsPath := h.dataPath

	// Читаем все файлы в папке
	files, err := os.ReadDir(graphsPath)
	if err != nil {
		return err
	}

	for _, file := range files {
		if file.IsDir() {
			continue
		}

		// Получаем имя файла без расширения
		fileName := file.Name()
		ext := filepath.Ext(fileName)
		nameWithoutExt := strings.TrimSuffix(fileName, ext)

		// Проверяем, поддерживается ли формат
		supportedExts := map[string]bool{
			".png":  true,
			".jpg":  true,
			".jpeg": true,
			".gif":  true,
			".svg":  true,
			".pdf":  true,
		}

		if !supportedExts[strings.ToLower(ext)] {
			continue
		}

		// Проверяем, есть ли информация об образце в лаб журнале
		sampleInfo, exists := h.labJournal.Samples[nameWithoutExt]
		project := "Uncategorized"
		description := ""

		if exists {
			project = sampleInfo.Project
			description = sampleInfo.Description
		}

		// Создаем или обновляем образец
		if existingSample, ok := newSamples[nameWithoutExt]; ok {
			// Добавляем график к существующему образцу
			existingSample.Graphs = append(existingSample.Graphs, models.Graph{
				Name: fileName,
				// URL для доступа через сервер (должен соответствовать статическому роутингу)
				FilePath: "/data/" + fileName,
				FileType: strings.TrimPrefix(ext, "."),
				IsMain:   len(existingSample.Graphs) == 0,
			})
			existingSample.HasMultiple = len(existingSample.Graphs) > 1
			newSamples[nameWithoutExt] = existingSample
		} else {
			// Создаем новый образец
			newSamples[nameWithoutExt] = models.Sample{
				Name:        nameWithoutExt,
				Project:     project,
				Description: description,
				CreatedAt:   time.Now(),
				Graphs: []models.Graph{
					{
						Name:     fileName,
						FilePath: "/data/" + fileName,
						FileType: strings.TrimPrefix(ext, "."),
						IsMain:   true,
					},
				},
				HasMultiple: false,
			}
		}
	}

	h.samples = newSamples
	return nil
}

// GetAllSamples возвращает все образцы
func (h *SampleHandler) GetAllSamples(w http.ResponseWriter, r *http.Request) {
	samples := make([]models.Sample, 0, len(h.samples))
	for _, sample := range h.samples {
		samples = append(samples, sample)
	}

	// Сортируем по имени
	sort.Slice(samples, func(i, j int) bool {
		return samples[i].Name < samples[j].Name
	})

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(samples)
}

// GetSample возвращает конкретный образец
func (h *SampleHandler) GetSample(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	name := vars["name"]

	sample, exists := h.samples[name]
	if !exists {
		http.Error(w, "Sample not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sample)
}

// ImportFromFolder импортирует графики из папки
func (h *SampleHandler) ImportFromFolder(w http.ResponseWriter, r *http.Request) {
	if err := h.RefreshSamples(); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Import completed successfully",
		"count":   string(rune(len(h.samples))),
	})
}
