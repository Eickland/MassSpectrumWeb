package models

import (
    "encoding/json"
    "fmt"
    "io/ioutil"
    "time"

    "github.com/xuri/excelize/v2"
)

// Sample представляет образец с его графиками
type Sample struct {
    Name        string    `json:"name"`
    Project     string    `json:"project"`
    Description string    `json:"description"`
    Graphs      []Graph   `json:"graphs"`
    CreatedAt   time.Time `json:"created_at"`
    HasMultiple bool      `json:"has_multiple"` // Для будущего использования (несколько графиков)
}

// Graph представляет график образца
type Graph struct {
    Name     string `json:"name"`
    FilePath string `json:"file_path"`
    FileType string `json:"file_type"` // png, jpg, svg и т.д.
    IsMain   bool   `json:"is_main"`   // Основной график для отображения
}

// Project представляет проект с образцами
type Project struct {
    Name        string   `json:"name"`
    Description string   `json:"description"`
    Samples     []Sample `json:"samples"`
    IsDefault   bool     `json:"is_default"` // Для несортированных образцов
}

// LabJournal данные из лабораторного журнала
type LabJournal struct {
    Samples     map[string]SampleInfo `json:"samples"`
    Projects    map[string]ProjectInfo `json:"projects"`
    LastUpdated time.Time              `json:"last_updated"`
}

// SampleInfo информация об образце из журнала
type SampleInfo struct {
    Name        string `json:"name"`
    Project     string `json:"project"`
    Description string `json:"description"`
    Notes       string `json:"notes"`
}

// ProjectInfo информация о проекте из журнала
type ProjectInfo struct {
    Name        string `json:"name"`
    Description string `json:"description"`
}

func NewLabJournal() *LabJournal {
    return &LabJournal{
        Samples:  make(map[string]SampleInfo),
        Projects: make(map[string]ProjectInfo),
    }
}

// LoadLabJournal загружает данные из Excel файла
func LoadLabJournal(path string) (*LabJournal, error) {
    f, err := excelize.OpenFile(path)
    if err != nil {
        return nil, fmt.Errorf("failed to open Excel file: %v", err)
    }
    defer f.Close()

    journal := NewLabJournal()

    // Предполагаем структуру Excel:
    // Лист "Samples": Name, Project, Description, Notes
    rows, err := f.GetRows("Samples")
    if err != nil {
        // Если нет листа Samples, пробуем первый лист
        sheets := f.GetSheetList()
        if len(sheets) > 0 {
            rows, err = f.GetRows(sheets[0])
        }
    }

    if err == nil && len(rows) > 1 {
        for _, row := range rows[1:] { // Пропускаем заголовок
            if len(row) >= 2 {
                sample := SampleInfo{
                    Name:    row[0],
                    Project: row[1],
                }
                if len(row) > 2 {
                    sample.Description = row[2]
                }
                if len(row) > 3 {
                    sample.Notes = row[3]
                }
                journal.Samples[sample.Name] = sample

                // Добавляем проект, если его еще нет
                if _, exists := journal.Projects[sample.Project]; !exists {
                    journal.Projects[sample.Project] = ProjectInfo{
                        Name:        sample.Project,
                        Description: fmt.Sprintf("Project %s", sample.Project),
                    }
                }
            }
        }
    }

    journal.LastUpdated = time.Now()
    return journal, nil
}

// Save сохраняет журнал в JSON (для кэширования)
func (lj *LabJournal) Save(path string) error {
    data, err := json.MarshalIndent(lj, "", "  ")
    if err != nil {
        return err
    }
    return ioutil.WriteFile(path, data, 0644)
}

// Load загружает журнал из JSON
func (lj *LabJournal) Load(path string) error {
    data, err := ioutil.ReadFile(path)
    if err != nil {
        return err
    }
    return json.Unmarshal(data, lj)
}