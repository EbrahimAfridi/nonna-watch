package app.nonnawatch.family

import androidx.lifecycle.ViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the family screen shows. A7 replaces the message with sign-in, timeline and alerts. */
data class FamilyUiState(
    val message: String = "Sign-in and the timeline come in task A7.",
)

class FamilyViewModel : ViewModel() {
    private val _state = MutableStateFlow(FamilyUiState())
    val state: StateFlow<FamilyUiState> = _state.asStateFlow()
}
