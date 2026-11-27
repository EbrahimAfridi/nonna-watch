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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import app.nonnawatch.core.Room

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) {
                    val appContext = LocalContext.current.applicationContext
                    ListenerScreen(viewModel { ListenerViewModel(ServiceListenerControl(appContext)) })
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
        modifier = Modifier.safeDrawingPadding().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Nonna Watch listener", style = MaterialTheme.typography.headlineSmall)
        Text("Status: ${state.status}")
        Text("Room", style = MaterialTheme.typography.titleMedium)
        Room.entries.forEach { room ->
            FilterChip(
                selected = room == state.room,
                onClick = { viewModel.selectRoom(room) },
                label = { Text(room.label) },
                enabled = !state.listening,
            )
        }
        if (state.listening) {
            Button(onClick = viewModel::stop) { Text("Stop listening") }
        } else {
            // Already-granted permissions come back at once, without a dialog.
            Button(onClick = { askPermissions.launch(permissionsToAsk()) }) {
                Text("Start listening")
            }
        }
    }
}

private fun permissionsToAsk(): Array<String> = buildList {
    add(Manifest.permission.RECORD_AUDIO)
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        add(Manifest.permission.POST_NOTIFICATIONS)
    }
}.toTypedArray()
