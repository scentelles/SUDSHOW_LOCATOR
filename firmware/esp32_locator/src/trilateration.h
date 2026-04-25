#pragma once
// =============================================================================
// Trilatération 2D — Calcul de position à partir de 3 distances
// =============================================================================

#include <Arduino.h>

struct Position2D {
    float x;
    float y;
    bool  valid;     // Résultat valide ?
    float quality;   // Qualité estimée (0.0 = mauvais, 1.0 = excellent)
};

class Trilateration {
public:
    Trilateration();

    /// Configure la position d'un anchor (index 0, 1 ou 2)
    void setAnchorPosition(uint8_t index, float x, float y);

    /// Calcule la position 2D à partir des 3 distances
    Position2D calculate(float d1, float d2, float d3);

    /// Applique un filtre passe-bas sur la position
    Position2D filter(const Position2D& raw, float alpha);

    /// Renvoie la dernière position filtrée
    Position2D getFilteredPosition() const;

    /// Reset le filtre (à appeler après changement de config)
    void resetFilter();

private:
    float _anchorX[3];
    float _anchorY[3];

    Position2D _filtered;
    bool       _filterInitialized;

    float estimateQuality(float d1, float d2, float d3, const Position2D& pos);
};
