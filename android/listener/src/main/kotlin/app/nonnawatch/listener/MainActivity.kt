package app.nonnawatch.listener

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import app.nonnawatch.core.Room
import app.nonnawatch.listener.settings.PrefsSettingsStore
import app.nonnawatch.listener.voice.QuestionLanguage

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) {
                    val appContext = LocalContext.current.applicationContext
                    ListenerScreen(
                        viewModel {
                            ListenerViewModel(
                                ServiceListenerControl(appContext),
                                PrefsSettingsStore(appContext),
                            )
                        },
                    )
                }
            }
        }
    }
}

@Composable
fun ListenerScreen(viewModel: ListenerViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    // Android asks the person; if the microphone is allowed, listening starts. The notification
    // permission is asked at the same time but is optional: the service runs without it.
    val askPermissions = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { granted ->
        if (granted[Manifest.permission.RECORD_AUDIO] == true) {
            viewModel.start()
        } else {
            viewModel.micPermissionDenied()
        }
    }

    Column(
        modifier = Modifier
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Nonna Watch listener", style = MaterialTheme.typography.headlineSmall)
        Text("Status: ${state.status}")
        if (state.hubStatus.isNotEmpty()) Text(state.hubStatus)
        if (state.questionStatus.isNotEmpty()) Text(state.questionStatus)

        if (state.listening) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = viewModel::togglePause) {
                    Text(if (state.paused) "Resume" else "Pause")
                }
                OutlinedButton(onClick = viewModel::stop) { Text("Stop listening") }
            }
        } else {
            // Already-granted permissions come back at once, without a dialog.
            Button(onClick = { if (viewModel.readyToStart()) askPermissions.launch(permissionsToAsk()) }) {
                Text("Start listening")
            }
        }

        Text("Hub", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = viewModel.hubUrl,
            onValueChange = viewModel::editHubUrl,
            label = { Text("Hub address") },
            placeholder = { Text("ws://192.168.43.12:8000/ws/listener") },
            singleLine = true,
            enabled = !state.listening,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = viewModel.token,
            onValueChange = viewModel::editToken,
            label = { Text("Token") },
            singleLine = true,
            enabled = !state.listening,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )

        Text("Room", style = MaterialTheme.typography.titleMedium)
        Room.entries.forEach { room ->
            FilterChip(
                selected = room == state.room,
                onClick = { viewModel.selectRoom(room) },
                label = { Text(room.label) },
                enabled = !state.listening,
            )
        }

        Text("Check-in question", style = MaterialTheme.typography.titleMedium)
        Text(
            "When the hub asks, the phone plays the family's recording, or speaks the question " +
                "itself, as an alarm. Test that it has a voice for the home's language:",
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            QuestionLanguage.entries.forEach { language ->
                FilterChip(
                    selected = language == state.testLanguage,
                    onClick = { viewModel.selectTestLanguage(language) },
                    label = { Text(language.label) },
                    enabled = !state.testing,
                )
            }
        }
        OutlinedButton(onClick = viewModel::testQuestion, enabled = !state.testing) {
            Text("Test the question")
        }
        if (state.testStatus.isNotEmpty()) Text(state.testStatus)
    }
}

private fun permissionsToAsk(): Array<String> = buildList {
    add(Manifest.permission.RECORD_AUDIO)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}.toTypedArray()
