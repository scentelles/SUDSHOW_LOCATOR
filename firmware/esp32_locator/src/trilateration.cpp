// =============================================================================
// Trilatération 2D — Implémentation
// =============================================================================
// Algorithme : Linéarisation par soustraction + résolution par Cramer
//
// Étant donné 3 anchors à (x1,y1), (x2,y2), (x3,y3) et les distances r1, r2, r3 :
//   (x-x1)² + (y-y1)² = r1²
//   (x-x2)² + (y-y2)² = r2²
//   (x-x3)² + (y-y3)² = r3²
//
// En soustrayant l'eq 1 des eq 2 et 3, on obtient un système linéaire 2×2.
// =============================================================================

#include "trilateration.h"
#include <math.h>

Trilateration::Trilateration()
    : _filterInitialized(false) {
    for (int i = 0; i < 3; i++) {
        _anchorX[i] = 0.0f;
        _anchorY[i] = 0.0f;
    }
    _filtered.x       = 0.0f;
    _filtered.y       = 0.0f;
    _filtered.valid    = false;
    _filtered.quality  = 0.0f;
}

void Trilateration::setAnchorPosition(uint8_t index, float x, float y) {
    if (index < 3) {
        _anchorX[index] = x;
        _anchorY[index] = y;
    }
}

Position2D Trilateration::calculate(float d1, float d2, float d3) {
    Position2D result;
    result.valid   = false;
    result.quality = 0.0f;

    float x1 = _anchorX[0], y1 = _anchorY[0];
    float x2 = _anchorX[1], y2 = _anchorY[1];
    float x3 = _anchorX[2], y3 = _anchorY[2];

    // Linéarisation : soustraire cercle 1 des cercles 2 et 3
    float eq_a1 = 2.0f * (x2 - x1);
    float eq_b1 = 2.0f * (y2 - y1);
    float eq_c1 = d1*d1 - d2*d2 - x1*x1 + x2*x2 - y1*y1 + y2*y2;

    float eq_a2 = 2.0f * (x3 - x1);
    float eq_b2 = 2.0f * (y3 - y1);
    float eq_c2 = d1*d1 - d3*d3 - x1*x1 + x3*x3 - y1*y1 + y3*y3;

    // Déterminant (règle de Cramer)
    float det = eq_a1 * eq_b2 - eq_a2 * eq_b1;

    // Vérification : si det ≈ 0, les anchors sont colinéaires → pas de solution
    if (fabsf(det) < 1e-6f) {
        return result;
    }

    result.x = (eq_c1 * eq_b2 - eq_c2 * eq_b1) / det;
    result.y = (eq_a1 * eq_c2 - eq_a2 * eq_c1) / det;
    result.valid = true;
    result.quality = estimateQuality(d1, d2, d3, result);

    return result;
}

Position2D Trilateration::filter(const Position2D& raw, float alpha) {
    if (!raw.valid) {
        return _filtered; // Garder la dernière position valide
    }

    if (!_filterInitialized) {
        _filtered = raw;
        _filterInitialized = true;
        return _filtered;
    }

    // Filtre passe-bas exponentiel (EMA)
    // filtered = alpha * raw + (1 - alpha) * filtered
    _filtered.x = alpha * raw.x + (1.0f - alpha) * _filtered.x;
    _filtered.y = alpha * raw.y + (1.0f - alpha) * _filtered.y;
    _filtered.valid = true;
    _filtered.quality = raw.quality;

    return _filtered;
}

Position2D Trilateration::getFilteredPosition() const {
    return _filtered;
}

void Trilateration::resetFilter() {
    _filterInitialized = false;
    _filtered.valid    = false;
}

float Trilateration::estimateQuality(float d1, float d2, float d3, const Position2D& pos) {
    // Qualité basée sur la cohérence des distances
    // On recalcule les distances depuis la position trouvée vers chaque anchor
    // et on compare avec les distances mesurées.

    float ex1 = sqrtf(powf(pos.x - _anchorX[0], 2) + powf(pos.y - _anchorY[0], 2));
    float ex2 = sqrtf(powf(pos.x - _anchorX[1], 2) + powf(pos.y - _anchorY[1], 2));
    float ex3 = sqrtf(powf(pos.x - _anchorX[2], 2) + powf(pos.y - _anchorY[2], 2));

    // Erreur moyenne en mètres
    float err = (fabsf(ex1 - d1) + fabsf(ex2 - d2) + fabsf(ex3 - d3)) / 3.0f;

    // Convertir en qualité : 0m d'erreur = 1.0, 1m d'erreur = 0.0
    float q = 1.0f - constrain(err, 0.0f, 1.0f);
    return q;
}
